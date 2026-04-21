# Codegen Refactor Design

## Problem Statement

The current codegen (codegen.py, ~20K lines) grew organically to support Python
features as they were needed. It works — Django/Wagtail runs, 50/50 stdlib imports
pass, 21/130 stdlib files compile natively — but has accumulated architectural debt
that makes further progress increasingly expensive:

1. **Type information is lost between stages.** A value starts as a known list pointer,
   gets stored as i64 in an FpyValue, gets loaded and unwrapped to i64, then crashes
   because the call site needed i8*. The type "list" was known at assignment but lost
   by the time it reaches the runtime call.

2. **Three incompatible value representations.** Bare LLVM types (i64/i8*/double),
   FpyValue structs ({i32, i64}), and string type tags ("int", "str", "list:int")
   exist in parallel with ad-hoc conversion between them.

3. **Error handling is "raise or crash."** When the compiler encounters a pattern it
   doesn't handle, it raises CodeGenError. The proper behavior for an AOT compiler
   targeting CPython compatibility is to fall back to the bridge — compile what you
   can, bridge what you can't.

## Design Principles

### P1: Every value carries its type
Every `_emit_expr_value` call returns `(ir.Value, ValueType)` — never a bare
`ir.Value` that the caller has to guess the type of.

### P2: One coercion layer, used everywhere
All runtime function calls go through `_rt_call(name, [(value, type), ...])` which
coerces arguments automatically. No bare `self.builder.call(self.runtime[...])`.

### P3: Bridge is the default, native is the fast path
When the compiler doesn't know how to handle something, it emits a bridge call.
Native codegen is an OPTIMIZATION applied when we have enough static type info.
The bridge path must always be correct; the native path must be at least as fast.

### P4: Fast paths are explicit opt-ins
The compiler generates the slow (correct) path first, then pattern-matches to
replace it with a fast path. For example:
- `len(x)` → default: `cpython_len(x)` → fast: `list_length(x)` when x is known list
- `x + y` → default: `cpython_binop(x, y, ADD)` → fast: `builder.add(x, y)` when both int
- `x.method()` → default: `cpython_method_call(x, "method")` → fast: `vtable_call(x, slot)` when class known

## Type System

### ValueType enum
Replace string tags with a proper type:

```python
from enum import Enum, auto

class VKind(Enum):
    INT = auto()      # i64 scalar
    FLOAT = auto()    # double scalar
    BOOL = auto()     # i32 (0 or 1)
    STR = auto()      # i8* to null-terminated string
    NONE = auto()     # literal 0
    LIST = auto()     # i8* to FpyList
    DICT = auto()     # i8* to FpyDict
    SET = auto()      # i8* to FpyDict (set-backed)
    TUPLE = auto()    # i8* to FpyList (is_tuple=1)
    OBJ = auto()      # i8* to FpyObj (native class instance)
    PYOBJ = auto()    # i8* to PyObject* (CPython bridge object)
    DECIMAL = auto()  # i8* to FpyDecimal
    COMPLEX = auto()  # i8* to FpyComplex
    BIGINT = auto()   # i8* to BigInt
    CLOSURE = auto()  # i8* to FpyClosure
    FVALUE = auto()   # {i32, i64} FpyValue (runtime-typed, unknown static type)
    UNKNOWN = auto()  # type not known at compile time

class ValueType:
    def __init__(self, kind: VKind, elem_type: 'ValueType | None' = None,
                 class_name: str | None = None):
        self.kind = kind
        self.elem_type = elem_type    # for LIST/DICT: element type
        self.class_name = class_name  # for OBJ: which class
    
    @property
    def is_ptr(self) -> bool:
        return self.kind in (VKind.STR, VKind.LIST, VKind.DICT, VKind.SET,
                             VKind.TUPLE, VKind.OBJ, VKind.PYOBJ, VKind.DECIMAL,
                             VKind.COMPLEX, VKind.BIGINT, VKind.CLOSURE)
    
    @property
    def llvm_type(self) -> ir.Type:
        if self.kind == VKind.FLOAT: return double
        if self.kind == VKind.BOOL: return i32
        if self.kind == VKind.FVALUE: return fpy_val
        if self.is_ptr: return i8_ptr
        return i64  # INT, NONE, UNKNOWN
    
    @property
    def fpy_tag(self) -> int:
        """FPY_TAG_* constant for this type."""
        return {VKind.INT: 0, VKind.FLOAT: 1, VKind.STR: 2, VKind.BOOL: 3,
                VKind.NONE: 4, VKind.LIST: 5, VKind.OBJ: 6, VKind.DICT: 7,
                VKind.SET: 9, VKind.BIGINT: 10, VKind.COMPLEX: 11,
                VKind.DECIMAL: 12, VKind.TUPLE: 5, VKind.PYOBJ: 6,
                VKind.CLOSURE: 6}.get(self.kind, 0)
```

### Typed values
Every expression emitter returns a `TypedValue`:

```python
@dataclass
class TypedValue:
    ir_val: ir.Value       # the LLVM IR value
    vtype: ValueType       # its static type
    
    def as_ptr(self, builder) -> ir.Value:
        """Coerce to i8* pointer."""
        if isinstance(self.ir_val.type, ir.PointerType):
            return self.ir_val
        if isinstance(self.ir_val.type, ir.IntType):
            return builder.inttoptr(self.ir_val, i8_ptr)
        # FpyValue: extract data field
        if self.vtype.kind == VKind.FVALUE:
            data = builder.extract_value(self.ir_val, 1)
            return builder.inttoptr(data, i8_ptr)
        return builder.inttoptr(builder.bitcast(self.ir_val, i64), i8_ptr)
    
    def as_i64(self, builder) -> ir.Value:
        """Coerce to i64."""
        if isinstance(self.ir_val.type, ir.IntType) and self.ir_val.type.width == 64:
            return self.ir_val
        if isinstance(self.ir_val.type, ir.PointerType):
            return builder.ptrtoint(self.ir_val, i64)
        if isinstance(self.ir_val.type, ir.IntType):
            return builder.zext(self.ir_val, i64)
        if isinstance(self.ir_val.type, ir.DoubleType):
            return builder.bitcast(self.ir_val, i64)
        if self.vtype.kind == VKind.FVALUE:
            return builder.extract_value(self.ir_val, 1)
        return self.ir_val
    
    def as_fv(self, builder) -> ir.Value:
        """Coerce to FpyValue {i32, i64}."""
        if self.vtype.kind == VKind.FVALUE:
            return self.ir_val
        tag = ir.Constant(i32, self.vtype.fpy_tag)
        data = self.as_i64(builder)
        fv = ir.Constant(fpy_val, ir.Undefined)
        fv = builder.insert_value(fv, tag, 0)
        fv = builder.insert_value(fv, data, 1)
        return fv
```

## Coercion Layer

### `_rt_call` becomes the universal call interface

```python
def _rt_call(self, name: str, args: list[TypedValue]) -> TypedValue:
    """Call a runtime function with automatic type coercion."""
    func = self.runtime[name]
    ret_type = self._rt_return_types[name]  # pre-registered
    
    coerced_args = []
    for tv, param in zip(args, func.args):
        coerced_args.append(self._coerce_to_llvm(tv, param.type))
    
    ir_result = self.builder.call(func, coerced_args)
    return TypedValue(ir_result, ret_type)

def _coerce_to_llvm(self, tv: TypedValue, target: ir.Type) -> ir.Value:
    """Coerce a TypedValue to match an LLVM parameter type."""
    if tv.ir_val.type == target:
        return tv.ir_val
    if isinstance(target, ir.PointerType):
        return tv.as_ptr(self.builder)
    if isinstance(target, ir.IntType) and target.width == 64:
        return tv.as_i64(self.builder)
    if isinstance(target, ir.IntType) and target.width == 32:
        v = tv.as_i64(self.builder)
        return self.builder.trunc(v, i32)
    if isinstance(target, ir.DoubleType):
        if isinstance(tv.ir_val.type, ir.IntType):
            return self.builder.sitofp(tv.ir_val, double)
        return tv.ir_val
    if target == fpy_val:
        return tv.as_fv(self.builder)
    return tv.ir_val
```

### Return type registry
Pre-register the return type of every runtime function:

```python
self._rt_return_types = {
    "list_new": ValueType(VKind.LIST),
    "list_length": ValueType(VKind.INT),
    "dict_new": ValueType(VKind.DICT),
    "dict_keys": ValueType(VKind.LIST, elem_type=ValueType(VKind.STR)),
    "str_concat": ValueType(VKind.STR),
    "str_len": ValueType(VKind.INT),
    "cpython_import": ValueType(VKind.PYOBJ),
    "cpython_getattr": ValueType(VKind.PYOBJ),
    "obj_new": ValueType(VKind.OBJ),
    # ... etc for all ~200 runtime functions
}
```

## Expression Emission

### Before (current)
```python
def _emit_expr_value(self, node) -> ir.Value:
    if isinstance(node, ast.Name):
        return self._load_variable(node.id, node)  # bare ir.Value, type unknown
    ...
```

### After (new)
```python
def _emit_expr(self, node) -> TypedValue:
    if isinstance(node, ast.Name):
        return self._load_variable(node.id)  # TypedValue with known type
    ...
```

Every caller gets both the value AND its type. No more guessing.

## Variable Storage

### Before
```python
self.variables[name] = (alloca, "list:int")  # string tag
```

### After
```python
self.variables[name] = (alloca, ValueType(VKind.LIST, elem_type=ValueType(VKind.INT)))
```

The `_store_variable` method wraps to FpyValue when `_USE_FV_LOCALS` is True.
The `_load_variable` method unwraps based on the stored `ValueType`.

## Bridge Fallback Architecture

### Default: bridge
Every operation has a bridge implementation that works for any type:

```python
def _emit_binop(self, node) -> TypedValue:
    left = self._emit_expr(node.left)
    right = self._emit_expr(node.right)
    
    # Fast path: both int → native add
    if left.vtype.kind == VKind.INT and right.vtype.kind == VKind.INT:
        if isinstance(node.op, ast.Add):
            return TypedValue(self.builder.add(left.as_i64(), right.as_i64()), 
                            ValueType(VKind.INT))
    
    # Fast path: both float → native fadd
    if left.vtype.kind == VKind.FLOAT and right.vtype.kind == VKind.FLOAT:
        if isinstance(node.op, ast.Add):
            return TypedValue(self.builder.fadd(left.ir_val, right.ir_val),
                            ValueType(VKind.FLOAT))
    
    # Fast path: str + str → str_concat
    if left.vtype.kind == VKind.STR and right.vtype.kind == VKind.STR:
        if isinstance(node.op, ast.Add):
            return self._rt_call("str_concat", [left, right])
    
    # Slow path: bridge (works for ANY type)
    op_code = {ast.Add: 0, ast.Sub: 1, ast.Mult: 2, ast.Div: 3,
               ast.FloorDiv: 4, ast.Mod: 5, ast.Pow: 6}.get(type(node.op), 0)
    return self._bridge_binop(left, right, op_code)

def _bridge_binop(self, left, right, op_code) -> TypedValue:
    """Universal binary operation via CPython bridge."""
    # Convert both to PyObject*, call PyNumber_Add/Sub/etc.
    out_tag = self._create_entry_alloca(i32, "bop.tag")
    out_data = self._create_entry_alloca(i64, "bop.data")
    self.builder.call(self.runtime["cpython_binop"],
                      [left.as_ptr(), 
                       ir.Constant(i32, right.vtype.fpy_tag), right.as_i64(),
                       ir.Constant(i32, op_code), out_tag, out_data])
    return TypedValue(
        self._fv_build_from_slots(self.builder.load(out_tag), self.builder.load(out_data)),
        ValueType(VKind.FVALUE))
```

### Method calls
```python
def _emit_method_call(self, node) -> TypedValue:
    receiver = self._emit_expr(node.func.value)
    method = node.func.attr
    
    # Fast path: known native class with vtable
    if receiver.vtype.kind == VKind.OBJ and receiver.vtype.class_name:
        cls_info = self._user_classes.get(receiver.vtype.class_name)
        if cls_info and method in cls_info.methods:
            return self._emit_native_method_call(receiver, cls_info, method, node)
    
    # Fast path: known list method
    if receiver.vtype.kind == VKind.LIST:
        if method == "append" and len(node.args) == 1:
            arg = self._emit_expr(node.args[0])
            self._rt_call("list_append_fv", [receiver, 
                          TypedValue(ir.Constant(i32, arg.vtype.fpy_tag), ValueType(VKind.INT)),
                          TypedValue(arg.as_i64(), ValueType(VKind.INT))])
            return receiver
        if method == "pop" and len(node.args) == 0:
            return self._rt_call("list_pop_int", [receiver])
        # ... other known list methods
    
    # Slow path: CPython bridge (works for ANY type)
    return self._bridge_method_call(receiver, method, node)
```

## Module Dispatch Registry

### Before
```python
if mod_name == "math":
    if func_name == "sqrt": ...
    if func_name == "sin": ...
elif mod_name == "json":
    if func_name == "dumps": ...
elif mod_name == "os":
    ...  # 500 lines of if/elif
```

### After
```python
# Registration (in __init__ or separate module):
self._module_handlers = {
    ("math", "sqrt"): lambda node: self._rt_call("math_sqrt", [self._emit_expr(node.args[0])]),
    ("math", "sin"): lambda node: self._rt_call("math_sin", [self._emit_expr(node.args[0])]),
    ("json", "dumps"): self._emit_json_dumps,
    ("json", "loads"): self._emit_json_loads,
    ("os", "getcwd"): lambda node: self._rt_call("os_getcwd", []),
    # ... all handlers registered here
}

def _emit_native_module_call(self, mod, func, node) -> TypedValue | None:
    handler = self._module_handlers.get((mod, func))
    if handler:
        return handler(node)
    return None  # fall through to bridge
```

## Migration Strategy

The rewrite doesn't need to happen all at once. The plan:

### Phase 1: TypedValue foundation
- Define `VKind`, `ValueType`, `TypedValue` classes
- Add `_emit_expr()` as a wrapper around `_emit_expr_value()` that infers type
- Add `_rt_call_typed()` alongside existing `_rt_call`
- No behavior changes, just new parallel API

### Phase 2: Expression emitters
- Convert `_emit_expr_value` callers one-by-one to use `_emit_expr`
- Each conversion is independently testable
- Start with leaf nodes (constants, variables), then operators, then calls

### Phase 3: Variable storage
- Replace string tags with `ValueType` in `self.variables`
- `_store_variable` and `_load_variable` use `ValueType`

### Phase 4: Bridge fallbacks
- Add bridge fallback to every operation that currently raises CodeGenError
- Delete all "Unsupported X" error paths — replace with bridge calls

### Phase 5: Module registry
- Convert the if/elif chain to a dispatch dict
- Each module handler becomes a small function or lambda

### Phase 6: Cleanup
- Remove old `_emit_expr_value` (replaced by `_emit_expr`)
- Remove old `_bare_to_tag_data` (replaced by `TypedValue.as_fv`)
- Remove old `_infer_type_tag` (replaced by `TypedValue.vtype`)
- Remove all scattered inttoptr/ptrtoint/bitcast (handled by coercion layer)

Each phase is a commit that passes all regression tests. If any phase breaks
something, we can revert to the previous phase.

## Performance Considerations

The fast paths MUST be preserved. The new architecture should generate identical
LLVM IR for hot paths:

- `x + y` where both are known ints → `add i64 %x, %y` (no change)
- `obj.method()` on known class → direct vtable call (no change)
- `lst.append(x)` on known list → `list_append_fv(lst, tag, data)` (no change)
- `for i in range(n)` → counted loop with `icmp` + `br` (no change)

The slow path (bridge fallback) is only used when type info is missing. This is
the correct tradeoff: correctness for unknown types, speed for known types.

## Testing

After each phase:
1. All existing regression tests pass (programs/classes, programs/algorithms, etc.)
2. Django+Wagtail test passes
3. Stdlib compilation count doesn't decrease (21/130 baseline)
4. Benchmark numbers don't regress (fib=175ms, loop=100ms, list=15ms)
