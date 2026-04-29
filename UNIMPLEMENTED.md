# Fastpy Python 3.14 Compatibility Status

Last updated 2026-04-28.

## Fully native (no CPython bridge)

### Core language
Loops (for/while/break/continue/else), functions (def, lambda, recursion,
defaults, *args, **kwargs, closures, nonlocal, global), classes (init,
methods, inheritance, super, multiple inheritance, nested classes,
full metaclass support, __slots__, staticmethod, classmethod, @property
get/set, __new__, __init_subclass__, __class_getitem__), decorators
(user decorators, decorator chaining, decorators with args),
@dataclass (native AST expansion),
@singledispatch (native switch dispatch).

### Operator overloading (dunders)
**Arithmetic**: __add__, __sub__, __mul__, __floordiv__, __truediv__,
__mod__, __pow__, __matmul__, __neg__, __pos__.
**Reverse**: __radd__, __rsub__, __rmul__, __rfloordiv__, __rtruediv__,
__rmod__, __rpow__, __rmatmul__ (e.g. `10 + obj` dispatches __radd__).
**Augmented**: __iadd__, __isub__, __imul__, __ifloordiv__, __itruediv__,
__imod__, __ipow__, __imatmul__, __ior__, __iand__, __ixor__,
__ilshift__, __irshift__.
**Bitwise**: __and__, __or__, __xor__, __lshift__, __rshift__,
__invert__, plus reverse variants (__rand__, __ror__, etc.).
**Comparison**: __eq__, __ne__, __lt__, __le__, __gt__, __ge__.
**Conversion**: __str__, __repr__, __int__, __float__, __bool__,
__abs__, __format__.
**Container**: __getitem__, __setitem__, __delitem__, __len__,
__contains__, __iter__/__next__, __call__, __hash__.

### Containers
list (literals, comprehensions, all methods incl. index with start/stop),
dict (literals, comprehensions, get, pop, pop with default, popitem,
setdefault, keys, values, items, update, copy, clear, fromkeys,
| merge, {**a, **b}),
tuple (literals, unpacking, *mid unpack, swap), set (literals, comprehensions,
add, discard, remove, union, intersection, difference, symmetric_difference,
issubset, issuperset, isdisjoint, copy, clear, pop, update,
|, &, -, ^, in — O(1) hash table), frozenset.

### Strings
f-strings (with =, !r, format specs), all common methods, % formatting,
.format(), raw strings, string multiplication, slicing, `in` operator.
Methods: lower, upper, strip/lstrip/rstrip, replace (with optional count),
split, rsplit, join, find, rfind, count, index, rindex (all with optional
start/end), startswith, endswith (with optional start/end and tuple support),
removeprefix, removesuffix, center, ljust, rjust (with optional fill char),
zfill, title, capitalize, swapcase, isdigit, isalpha, isalnum, isspace,
isupper, islower, istitle, isidentifier, isprintable, isdecimal, isnumeric,
casefold, encode, expandtabs, partition, rpartition, splitlines,
maketrans (2-arg), translate.

### Number methods
int: bit_length, bit_count (LLVM inline — ctlz/ctpop intrinsics),
to_bytes(length, byteorder).
float: is_integer (LLVM inline — floor comparison),
as_integer_ratio (C runtime — returns tuple).
int.from_bytes(bytes, byteorder) — class method.

### Exceptions
try/except/finally/else, raise, bare raise, raise from, multiple except
types, except* (ExceptionGroup) — all native.

### Generators & Iterators
yield, yield from (native delegation via while+send expansion),
generator expressions, native send/close/throw (state-machine compilation
for yield-as-expression generators), iterator protocol (__iter__/__next__),
finally cleanup on GC via per-class destructor.

### Async
async def, await compiled natively (synchronous execution).
asyncio.run(), asyncio.gather(), asyncio.sleep() — all native.

### Pattern matching
match/case with literal, capture, guard, or, wildcard, sequence, singleton
patterns. Tested: literal, string, capture, wildcard, or, guard, sequence,
nested sequence, singleton (None/True/False), mixed singleton+literal.

**Missing pattern types**: none — all pattern types are now implemented.

**Formerly missing, now implemented:**
- `MatchStar` — `case [first, *rest]:` captures remaining elements into
  a sub-list. Supports prefix-only (`[first, *rest]`), suffix-only
  (`[*rest, last]`), and both (`[first, *mid, last]`). Unnamed star
  (`*_`) acts as wildcard.
- `MatchMapping` — `case {"key": val}:` matches dict structure by
  probing for each key. Uses safe lookup (`dict_get_fv_safe`) that
  returns NONE for missing keys instead of raising KeyError. Supports
  nested pattern matching on values.
- `MatchClass` — `case Point(x=1, y=2):` and `case int(n):`. Supports
  builtin type patterns (int/str/float/bool/list/dict), user class
  keyword patterns, and positional patterns via `__match_args__`.
  isinstance check short-circuits before slot reads to prevent
  cross-class memory access.

### Imports (native)
math module (direct libm calls), json module (native parser/serializer),
os/os.path module (direct Win32/POSIX API calls).

### Builtins
print, range, len, sorted (with key=, reverse=), int, float, str, bool,
abs, sum, min, max, list, reversed, set, frozenset, enumerate, zip,
isinstance, type, any, all, hash, next, iter, eval (compile-time for
literals), exec (compile-time for literals), repr, pow, divmod, chr, ord,
hex, oct, bin, round, dict, tuple, map, filter, complex, locals, globals,
getattr/setattr/hasattr/delattr, input, open.

### Numbers
int (i64), float (f64), BigInt (speculative unboxing with overflow fallback),
complex (native FpyComplex with arithmetic).

Per-variable integer overflow control via `typing.Annotated` markers and
constructor functions, in both 64-bit and 32-bit widths:
- `Annotated[int, Unchecked]` / `unchecked_int()` — raw LLVM i64 add/sub/mul,
  wraps silently on overflow (C / two's-complement semantics).
- `Annotated[int, Checked]` / `checked_int()` — LLVM i64 overflow intrinsics,
  raises OverflowError on overflow (no BigInt fallback).
- `Annotated[int, Unchecked32]` / `unchecked_int32()` — raw LLVM i32
  add/sub/mul, wraps at the 32-bit boundary.  Values stored as i64
  internally, arithmetic truncated to i32 and sign-extended back.
- `Annotated[int, Checked32]` / `checked_int32()` — LLVM i32 overflow
  intrinsics, raises OverflowError at the 32-bit boundary.
- Default (no annotation) — runtime `checked_*` functions with BigInt fallback.

The `fastpy` shim package provides CPython-compatible implementations
so annotated code runs identically under CPython for development/testing.
Augmented assignment (`x += 1`) is handled for all modes.

### Threading
Three modes: none (default), GIL, free-threaded (per-object locks).

### eval/exec
Literal string arguments compiled inline at compile time (zero overhead,
supports nested eval/exec). Dynamic strings route through CPython bridge
with automatic locals namespace injection.

## Routes through CPython bridge

These features work correctly but use the embedded CPython interpreter:

- **`re` module** — full regex engine impractical to reimplement natively
- **`.pyd` imports** (numpy, etc.) — C extensions inherently need CPython
  for PyObject* marshalling. The extension's own C code runs natively.
- **Dynamic eval()/exec()** with non-literal string arguments
- **Other stdlib modules** not implemented natively (e.g., collections,
  itertools, functools — except singledispatch which is native)

## Bugs fixed (2026-04-28, tuple repr, bytes length, dict comp filter, deque, struct, callable)

### 94. Dict comprehension with tuple-unpacking target ignored if-clause filter (fixed)
`{k: v for k, v in d.items() if v > 2}` included ALL items instead of only
those matching the filter. The tuple-unpacking path in `_emit_dict_comprehension`
had no filter handling — the `gen.ifs` list was completely ignored.
Fix: Added filter handling (condition check → cbranch to skip/add blocks) in
the tuple-unpacking dict comprehension path, matching the existing logic in
the simple-variable path.

### 93. `len()` on bytes with embedded null bytes returned 0 (fixed)
`struct.pack(">I", 12345)` produces 4 bytes starting with `\x00\x00`. Calling
`len()` on the result returned 0 because `fastpy_str_len` uses `strlen()` which
stops at the first null byte.
Root cause: Bytes were stored as raw `char*` with no length metadata. Binary
data containing null bytes was truncated by all `strlen`-based operations.
Fix: Added `FpyBytes` struct with explicit `length` field (alongside magic and
refcount, like FpyString). `struct.pack` and `str.encode` now allocate via
`fpy_bytes_alloc` which preserves the length. Added `fastpy_bytes_len` which
checks for FpyBytes header and reads the stored length, falling back to
`strlen` for plain strings. Updated `_emit_builtin_len` to route VKind.BYTES
through `bytes_len` instead of `str_len`.

### 92. `list(bytes_obj)` returned empty list (fixed)
`list(b)` where `b = "hello".encode("utf-8")` returned `[]` instead of
`[104, 101, 108, 108, 111]`. The `list()` constructor had no bytes-specific
handler, so it fell through to the generic path which returned the bytes pointer
as-is (not a list).
Fix: Added `fastpy_bytes_to_list` runtime function that iterates byte values
and builds an FpyList of ints. Added `list(bytes)` handler in codegen that
checks the variable's type tag and dispatches to `bytes_to_list`.

### 91. Tuple slicing and `tuple()` constructor returned lists (fixed)
`t[1:4]` on a tuple printed `[20, 30, 40]` (list syntax) instead of
`(20, 30, 40)` (tuple syntax). Similarly, `tuple(x**2 for x in range(5))`
printed with square brackets. The `is_tuple` flag on FpyList was not
propagated.
Root cause: `fastpy_list_slice` and `fastpy_list_slice_step` created new
`fpy_list_new()` results without copying `is_tuple` from the source. The
`tuple()` constructor called `list_new` instead of `tuple_new` for empty
tuples, and `tuple(iter)` didn't mark the result as tuple.
Fix: (1) Propagate `is_tuple` in both slice functions; (2) `tuple()` uses
`tuple_new`; (3) `tuple(iter)` calls `fastpy_list_mark_tuple` after building.

### 90. struct module routed through CPython bridge instead of native handlers (fixed)
`struct.pack("<HH", 1000, 2000)` followed by `struct.unpack("<HH", packed)`
crashed with access violation (exit code 3221225477). Single-value pack/unpack
worked but multi-value round-trips segfaulted.
Root cause: `"struct"` was missing from the `_NATIVE_MODULES` set. The gate
`if mod_name in self._NATIVE_MODULES` at the top of `_emit_native_module_call`
exited early, so all struct operations fell through to the CPython bridge.
The bridge returned `bytes` as a PyObject* which was then passed incorrectly
to subsequent bridge calls, corrupting memory.
Fix: Added `"struct"` to `_NATIVE_MODULES` so pack/unpack dispatch to the
native `fastpy_struct_pack`/`fastpy_struct_unpack` runtime functions.
Also added correct return type tags ("bytes" for pack, "tuple" for unpack)
in `_infer_type_tag`.

### 89. Deque len/for always returned 0 or empty due to VKind.LIST misdispatch (fixed)
`len(d)` on a `collections.deque` always returned 0, and `for x in d` never
iterated. Other deque operations (append, appendleft, popleft, extend) worked.
Root cause: `ValueType.from_old_tag("deque")` maps to `VKind.LIST`, so both
`_emit_builtin_len` and `_emit_for` dispatched to the list fast paths
(`list_length` / `_emit_for_list`). But FpyDeque has a different struct layout
than FpyList — `length` is at offset 4 (after head) in deque vs offset 2 in
list — so `list_length` read the wrong field (always 0).
Fix: Added explicit `_is_deque_expr()` / `tag == "deque"` checks BEFORE the
`VKind.LIST` fast paths in both `_emit_builtin_len` and `_emit_for`, routing
to `deque_length` and `_emit_for_deque` (which converts to list first via
`deque_to_list`) respectively.

### 88. Callable parameter monomorphization hardcoded first caller (fixed)
`apply(func, x)` called with multiple different callables (named function,
lambda, closure) always dispatched to the first function seen during
call-site analysis. `apply(double, 5)` returned 10 (correct), but
`apply(lambda x: x+1, 10)` also returned 20 (calling `double` instead of
the lambda), and `apply(add5, 3)` segfaulted (calling `double` with a
closure struct pointer).
Root cause: `_param_func_map` recorded the first function name seen for
each (func_name, param_index) pair and used it unconditionally as an alias,
causing `_func_aliases` to map the parameter name to a single LLVM function.
Fix: (1) call-site analysis now invalidates `_param_func_map[key] = None`
when non-function arguments (closures, lambdas, non-Name variables) are
passed at the same call site; (2) function body compilation tags ambiguous
callable parameters (where `_param_func_map` is None) as `"closure"` kind
in `self.variables`, causing them to dispatch through `call_ptr` (which
auto-detects closure struct vs raw function pointer via `FPY_CLOSURE_MAGIC`)
instead of being hardcoded to a single function.

### 87. Multiple decorator chaining called wrong inner function (fixed)
`@add_one @double_result def cube(x)` produced `x³*4` instead of `x³*2+1`.
Two root causes:
(a) Closure name collision: `_emit_nested_funcdef` found closures by suffix
match (`full_name.endswith(".wrapper")`), so when both `double_result` and
`add_one` defined inner functions called `wrapper`, the first match in
`_closure_info` was always used. Fix: match by fully qualified name
(`outer_func.inner_func`) using `_current_func_name` context.
(b) Decorator application order: the decorator loop iterated forward
(`[d1, d2]`) and always used the original function pointer for each
decorator. Python semantics require bottom-up application: `@d1 @d2 def f`
means `f = d1(d2(f))`. Fix: iterate `reversed(active_decos)` and chain
results — each decorator receives the previous decorator's output as
`func_ptr`, not the original function.

### 86. Augmented assignment on attributes missing string/list/OBJ support (fixed)
`self.name += " Smith"` printed a raw pointer value instead of the
concatenated string. `self.items += [new]` and `self.vec += Vec(1,2)` also
failed. Root cause: the attribute augmented assignment path only checked for
`DoubleType` (float) vs everything-else (int), with no handlers for string
concatenation, list operations, or OBJ dunder dispatch (`__iadd__` etc.).
Fix: added string concat (pointer+pointer with Add → `str_concat`), list
concat/repeat, and OBJ `__iadd__`/`__isub__`/etc. dispatch to the
`ast.Attribute` target path in `_emit_aug_assign`, mirroring the existing
`ast.Name` target dispatch.

### 85. FpyValue struct in comparisons crashed with type mismatch (fixed)
Comparisons where one operand was an FpyValue struct `{i32, i64}` (from
tuple unpacking, `dict.get()`, etc.) and the other was a scalar (i64 or
double) fell through to `_emit_int_compare` with mismatched types.
Fix: expanded the FpyValue comparison handler from requiring BOTH operands
to be FpyValue to requiring EITHER operand. The non-FpyValue side is
converted to `(tag, data)` via `_to_tag_data_ir` and both sides are
dispatched through `fv_compare` for runtime-tag-aware comparison.

### 84. FpyValue struct in float/int binops crashed (fixed)
`x + 0.5` where `x` came from tuple unpacking (UNKNOWN-typed) crashed
with "Operands must be the same type, got (double, {i32, i64})". The
FpyValue struct flowed into `_emit_float_binop` as a raw struct alongside
a double operand. Fix: added FpyValue-to-double unwrapping at the top of
`_emit_float_binop` (tag-aware: float→bitcast, int→sitofp), FpyValue-to-i64
extraction in `_emit_int_binop`, and full tag-aware FpyValue handling in
`_emit_aug_assign`. This fixed the bm_nbody benchmark compilation
(305ms vs CPython 1058ms, ~3.5x faster).

## Bugs fixed (2026-04-28, decorator application & UNKNOWN/FV arithmetic)

### 83. Decorator application crashed or called original function (fixed)
`@identity def greet(name)` crashed with access violation; `@double_result
def square(x)` called the original function (returned 9 instead of 18).
Three root causes:
(a) Closure FpyValue tag: `VKind.CLOSURE.fpy_tag` returned 6 (OBJ), so
`fpy_rc_incref` dereferred the function pointer as an FpyObj* struct.
Fix: changed CLOSURE fpy_tag to 0 (INT) and added CLOSURE to the scalar
fast path so refcount operations are skipped entirely.
(b) ABI mismatch: `call_ptr1` calls functions with bare i64 ABI, but
FV-ABI functions expect `{i32, i64}` (FpyValue) structs. When `@identity`
returned the raw function pointer and `call_ptr1` called it, the i64
argument was misinterpreted as a struct pointer.
Fix: decorator application now creates an i64-ABI wrapper for FV-ABI
functions (via `_get_or_emit_i64_wrapper`) so the function pointer stored
in the closure variable is always i64-ABI-compatible.
(c) Dispatch priority: `_load_or_wrap_fv` checked `self._user_functions`
before `self.variables` for closure tag, so decorated functions were
dispatched directly to the original LLVM function, bypassing the closure
variable. Fix: moved closure variable check before user function check.
Also fixed: `_emit_closure_call` now uses `call_ptr` (auto-detects closure
vs raw pointer via magic number) instead of `closure_call` (assumes
closure struct). The i64 wrapper now forwards the return tag via
`set_ret_tag` for correct runtime type dispatch.

### 81. dict.get() counter pattern produced float instead of int (fixed)
`d[k] = d.get(k, 0) + 1` stored float values (printed as `5.0` instead of
`5`). Root cause: `dict.get()` returns an FpyValue with VKind.UNKNOWN. The
UNKNOWN BinOp path unconditionally promoted both operands to `double` via
`sitofp`/`bitcast` and called `_emit_float_binop`, losing int-ness. Fix:
added runtime-tag-aware branching in `_emit_binop` for UNKNOWN+INT and
UNKNOWN+UNKNOWN operands. When the UNKNOWN tag is INT at runtime, integer
arithmetic is used; when FLOAT, float arithmetic. The result is returned as
an FpyValue with the correct runtime tag. Also fixed the Safety block
fallback for FpyValue structs to use `select(is_float, bitcast, sitofp)`
instead of always bitcasting.

### 82. `int(float_param)` returned float in monomorphized functions (fixed)
`def to_int(x): return int(x)` called with a float argument printed `3.0`
instead of `3`. Root cause: the return-type analysis in
`_declare_user_function` walked the entire return expression `int(x)` with
`ast.walk`, found `x` in `float_params`, and set `ret_type = double`. It
didn't understand that `int()` always returns an integer regardless of
argument type. Fix: added a check for int-returning builtins (`int`, `len`,
`ord`, `hash`, `id`, `abs`, `round`) — when the return expression is one
of these calls, the float-parameter walk is skipped. Pre-existing bug.

## Bugs fixed (2026-04-28, method returns, comprehensions & type inference)

### 68. Property/method truediv return type (fixed)
`return self._c * 9 / 5 + 32` in a property getter or method returned
`212` (int) instead of `212.0` (float). Root cause: method return type
analysis defaulted to `i64` and had no check for `ast.Div` (Python's `/`
always returns float). The `double` result was silently truncated to `i64`
via `fptosi` in `_emit_return`. Fix: added `ast.Div` detection in the
return-expression `ast.walk` scan — any expression containing truediv
now sets `ret_type = double`.

### 69. Dict comprehension with non-range iterators (fixed)
`{w: len(w) for w in words}` crashed when `words` was a list variable
(not `range()`). Dict comprehensions only supported `range()` iterators,
falling back to CPython bridge for everything else. Fix: added native
list/tuple/set/dict/string iteration path in `_emit_dict_comprehension`.
Properly tracks element types (string keys from string lists, dict key
iteration yields strings). Supports filter conditions.

### 70. Nested dict subscript access crashed (fixed)
`config["database"]["host"]` crashed when `config` was a mixed-type dict
literal (`{"database": {...}, "debug": True}`). Root cause: chained
subscript `config["database"]["host"]` — `_is_dict_expr` didn't check
per-key types from `_dict_var_key_types`, so the intermediate subscript
wasn't recognized as a dict. Fix: (a) added per-key type lookup to
`_is_dict_expr` for subscripts on dicts with per-key type info;
(b) extended `_infer_constant_value_type` to recognize dict/list/tuple/set
literals and user class constructors, so mixed-type dict per-key maps
include container values.

### 71. Keyword-only args after `*args` (fixed)
`def f(*args, sep=", "):` — keyword-only parameters after `*args` were
not included in the function signature, causing missing arguments at call
sites. Fix: comprehensive update across declaration (both vararg-only and
mixed-vararg paths), body (FV local storage with correct type inference),
and call-site emission (keyword matching with default fallback). The
`FuncInfo` dataclass gained `n_kwonly` to track kwonly parameter count.

### 72. Mixed vararg positional param type inference (fixed)
`def show(msg, *args):` where `msg` was a string — positional params in
mixed-vararg functions defaulted to `i64` even when call-site analysis
returned "str". Fix: added full type checking for positional params in
the mixed-vararg declaration path (str/list/dict/obj → i8_ptr).

### 73. Nested tuple unpacking (fixed)
`(a, b), c = (1, 2), 3` and similar nested tuple targets crashed or
silently failed. Fix: added recursive `_emit_tuple_unpack` calls for
`ast.Tuple`/`ast.List` targets in both the direct-tuple and list-unpack
paths. Supports arbitrary nesting depth.

### 74. `super().__init__()` type propagation (fixed)
`super().__init__("circle")` in a child class constructor — the parent's
`name` parameter was typed as "int" because the heuristic child→parent
propagation (`Circle(5)` → `Shape(5)`) ran first and wasn't overridden.
Fix: added explicit super() call scanning that propagates argument types
to parent class/method, with unconditional override (super() args are
more accurate than the heuristic propagation).

### 75. Dict `in` operator: string variable dispatch (fixed)
`x = "hello"; print(x in cache)` inside a function printed `False` instead
of `True`. Root cause: FV-backed string variables are loaded as i64 (data
field of FpyValue), so `isinstance(left_val.type, ir.IntType)` was True,
routing through `dict_has_int_key` (integer hash table) instead of
`dict_has_key` (string hash table). Fix: pass `left_kind` (VKind from
TypedValue) from `_emit_compare` into `_emit_in_compare`; when
`left_kind == VKind.STR`, convert i64 → i8* via inttoptr and use
`dict_has_key`.

### 76. Global containers invisible inside functions (fixed)
Global dicts, sets, tuples accessed inside functions were not recognized
by `_infer_type_tag`, `_is_dict_expr`, `_is_set_expr`, `_is_tuple_expr`
because these only checked `self.variables` (function-scoped, starts empty)
and not `self._global_vars`. Fix: all four functions now check
`_global_vars` as fallback when the variable is not in `self.variables`.
Also fixed `_is_set_expr` fallback (was completely missing).

### 77. Global set/tuple variables declared as i64 (fixed)
`valid = {"a", "b", "c"}` at module level — when referenced from a
function, the auto-created global variable was `i64` with tag "int"
because `global_types` had no case for `ast.Set`/`ast.SetComp`/`ast.Tuple`.
The pointer was stored via `ptrtoint` into i64, but type info was lost.
Fix: added set/tuple detection to `global_types` dictionary, and added
"set"/"tuple" to the pointer-type checks in both global creation blocks.

### 78. `type(x) == int` always returned False (fixed)
`type(x) == int`, `type(x) is str`, etc. always returned `False` because
`type()` returned a CPython type object pointer that didn't compare equal
to the builtin type name (also a CPython object). Fix: added
`_try_fold_type_compare` that pattern-matches `type(arg) == <builtin>`
and folds to a compile-time constant when the argument's VKind is known.
Supports `==`, `!=`, `is`, `is not` with all builtin types (int, float,
str, bool, list, dict, set, tuple, bytes, complex). For FV-backed
variables with unknown compile-time type, emits a runtime FpyValue tag
check.

### 79. `int(string_param)` returned raw pointer (fixed)
`int(s)` where `s` is an FV-backed string parameter returned the raw
pointer value instead of parsing the string. Root cause: the FV-backed
`int()` path only checked for `FPY_TAG_FLOAT` (float→int conversion) and
fell through to returning `fv_data` as-is for all other tags. For string
values, `fv_data` is `ptrtoint(str_ptr)`, not a parseable integer.
Fix: added 3-way runtime branch — float tag → `fptosi`, string tag →
`str_to_int(inttoptr(data))`, else → return data directly.

### 80. `float(string_param)` returned raw pointer bits (fixed)
Same pattern as bug #79 for `float()`. FV-backed string parameters hit
the `isinstance(val.type, ir.IntType)` path which called `sitofp`,
interpreting the raw pointer bits as an integer and converting to float.
Fix: added 3-way FV runtime branch — str tag → `str_to_float`, float
tag → bitcast, else (int/bool) → `sitofp`.

## New methods (2026-04-28, method coverage expansion)

### 43. `int.bit_length()` and `int.bit_count()` (new)
Compiled inline using LLVM intrinsics `llvm.ctlz` (count leading zeros)
and `llvm.ctpop` (population count). Both handle negative values via
`abs()` before counting. Zero special-cased for `bit_length`.
Note: `llvm.ctlz` requires explicit `fnty` parameter with 2-arg signature
`(i64, i1)` — `declare_intrinsic` alone generates a 1-arg function.

### 44. `float.is_integer()` (new)
Compiled inline using `llvm.floor` intrinsic: `floor(x) == x`. Returns
`i32` (not `i64`) so `_fv_wrap` correctly tags the result as BOOL
(prints `True`/`False` not `1`/`0`).

### 45. Seven new string methods (new)
`str.rsplit(sep, maxsplit)`, `str.casefold()`, `str.istitle()`,
`str.isidentifier()`, `str.isprintable()`, `str.isdecimal()`,
`str.isnumeric()`. All with C runtime implementations and codegen dispatch.

### 46. Full set method dispatch (new)
`set.union()`, `set.intersection()`, `set.difference()`,
`set.symmetric_difference()`, `set.issubset()`, `set.issuperset()`,
`set.isdisjoint()`, `set.copy()`, `set.clear()`, `set.pop()`,
`set.update()`. Runtime functions for issubset/issuperset/isdisjoint/
copy/clear/pop/update are new. Union/intersection/difference/symmetric_diff
existed in runtime but had no codegen dispatch.

### 47. `dict.popitem()`, `dict.copy()` (new)
`dict.popitem()` removes and returns the last (key, value) pair as a
tuple. `dict.copy()` returns a shallow copy with correct "dict" type tag.
Also fixed: `_infer_type_tag` and `_is_dict_expr` now recognize
`dict.copy()` return type, and `_is_set_expr` recognizes set method
return types.

### 48. `dict.pop(key, default)` two-argument form (new)
`d.pop("key", fallback)` returns the value if found, or the default.
Uses `dict_pop_fv` with FpyValue-based default via out parameters.

### 49. `str.index()`, `str.rindex()` (new)
Like `str.find()`/`str.rfind()` but raise `ValueError` when substring
is not found. Uses `fastpy_str_index_sub`/`fastpy_str_rindex_sub`
C runtime functions (different names from `str_index` which is used
for subscript indexing `s[i]`).

### 50. `str.replace(old, new, count)` three-argument form (new)
`s.replace("a", "x", 2)` replaces at most `count` occurrences.
Uses `fastpy_str_replace_count` C runtime function.

### 51. String methods with `start`/`end` parameters (new)
`str.find(sub, start, end)`, `str.rfind(sub, start, end)`,
`str.count(sub, start, end)`, `str.index(sub, start, end)`,
`str.rindex(sub, start, end)`, `str.startswith(prefix, start, end)`,
`str.endswith(suffix, start, end)`. All use `_range` C runtime
variants with Python-style negative index clamping.

### 52. `str.startswith(tuple)`, `str.endswith(tuple)` (new)
`s.startswith(("http", "ftp"))` checks any prefix in the tuple.
Uses `fastpy_str_startswith_tuple`/`fastpy_str_endswith_tuple` runtime
functions that iterate an FpyList of prefixes/suffixes.

### 53. `list.index(value, start, stop)` with range (new)
`lst.index(20, 2)` and `lst.index(20, 2, 4)` search within a slice.
Raises `ValueError` if not found (matching CPython behavior).

### 54. `bytes.decode()` (new)
`b"hello".decode()` returns a string. For ASCII/UTF-8 content, the
bytes are the string (zero-copy for compatible encodings).

### 55. `dict.fromkeys(keys)` and `dict.fromkeys(keys, value)` (new)
Class method to create a dict from an iterable of keys. Default value
is `None` when not specified.

### 56. `float.as_integer_ratio()` (new)
Returns the exact integer ratio as a `(numerator, denominator)` tuple.
C runtime implementation using `frexp()` decomposition with GCD
simplification. Handles 0.0, raises ValueError for NaN/Inf.

### 57. `int.to_bytes(length, byteorder)` (new)
Converts an integer to a bytes string of the given length. Supports
`"big"` and `"little"` byteorder. Note: bytes with embedded `\x00`
may truncate due to null-terminated char* representation.

### 58. `int.from_bytes(bytes, byteorder)` (new)
Class method to convert a bytes string to an integer. Supports
`"big"` and `"little"` byteorder.

### 59. `list.sort(key=...)` fix (fixed)
Previously, `list.sort(key=len)` would silently ignore the `key=`
parameter and sort by natural ordering. Now correctly detected and
falls through to CPython bridge for correct key-based sorting.

### 60. `str.lstrip(chars)`, `str.rstrip(chars)` (new)
`str.lstrip("xy")` and `str.rstrip("xy")` with character set argument.
Previously only the no-args (whitespace) versions were supported.

### 61. `dict.clear()` (new)
Resets dict length to 0 and clears the index table. Was listed as
implemented in the Containers section but had no actual codegen
dispatch or runtime function.

### 62. `list.index(str)`, `list.count(str)` (new)
String-value versions of `list.index` and `list.count`. Previously
only worked with int values. Now dispatches to `list_index_str` /
`list_count_str` when the argument is a pointer type (string).

### 63. `str.maketrans()` and `str.translate()` (new)
`str.maketrans("aeiou", "12345")` creates a 257-byte translation
table (magic byte + 256-char mapping). `s.translate(table)` applies
it. Table uses offset-1 indexing to avoid null-byte C string issues.
Supports the 2-arg form of maketrans (from/to character mapping).

### 64. Comprehensive operator overloading (new)
Full dunder dispatch for user classes. Forward operators (__add__ etc.)
dispatch via `obj_call_method1`. Reverse operators (__radd__ etc.)
dispatch when the right operand is an object and the left is a scalar.
Augmented assignment (__iadd__ etc.) dispatches in `_emit_aug_assign`.
Bitwise operators (__and__, __or__, __xor__, __lshift__, __rshift__,
__invert__) dispatch through the same mechanism. `int(obj)` → __int__,
`float(obj)` → __float__ (uses double-returning ABI variant
`obj_call_method0_double`). `f"{obj:spec}"` → __format__ with fallback
to __str__ + format_spec_str.

### 65. Context manager exception suppression (fixed)
`with` statement now checks __exit__ return value. If __exit__ returns
a truthy value and there is a pending exception, the exception is
cleared (suppressed). Works for both native FpyObj and PyObject bridge
context managers.

### 66. `repr(obj)` and `str(obj)` dunder dispatch (new)
`repr(obj)` now dispatches to `__repr__` (falls back to `__str__`,
then `<ClassName object>`). `str(obj)` dispatches to `__str__`.
Previously both used `__str__`. Runtime: `fastpy_obj_to_repr` for repr,
`fastpy_obj_to_str` for str. Also fixed `fastpy_fv_str` OBJ case to
call `__str__` directly (was routing through `fpy_value_repr` which
now calls `__repr__`). CPython bridge PyObject* values use
`PyObject_Repr` for repr.

### 67. Mixed-type runtime comparison (`fastpy_fv_compare`) (new)
Functions called with both int and str arguments at different call sites
now compare correctly. Added `fastpy_fv_compare(tag1, data1, tag2, data2, op)`
runtime function that dispatches based on runtime tags: STR uses strcmp,
FLOAT uses double comparison, INT uses i64 comparison. Codegen detects
"mixed"-tagged variables via `_is_mixed_var()` and re-loads the full
FpyValue (with runtime tag) for comparison instead of using the raw i64
data extracted by `_emit_expr_value`. Fixes the `test_bisect` grade
example and similar patterns.

## Bugs fixed (2026-04-28, bridge dispatch & string methods)

### 39. `len()` on bytes literals crashed (fixed)
`len(b"hello")` caused an access violation. `_emit_builtin_len` had no
handler for `VKind.BYTES` — it fell through to `cpython_len` which
expects a PyObject*, but bytes are stored as native `char*` pointers.
Fix: Added `VKind.BYTES` alongside `VKind.STR` in the `str_len` fast path.

### 40. Bridge call results crashed on `len()`, `print()`, and other builtins (fixed)
`from _struct import pack; data = pack('i', 42); len(data)` crashed.
Bridge calls return FpyValue structs (tag+data) stored in `{i32, i64}`
allocas, but PYOBJ-tagged variables were treated as raw PyObject*
pointers. `len()` passed the FpyValue data field (a native bytes
pointer) to `cpython_len` (expects PyObject*). Same crash with `print()`.
Fix: Extended `_emit_builtin_len`, `_emit_print_single`, and
`_load_or_wrap_fv` to check `_load_fv_raw` before assuming a raw pointer.
FpyValue-backed PYOBJ variables now route through `fv_len`/`fv_print`
runtime dispatch, which correctly handles all native types.

### 41. Missing string methods: removeprefix, removesuffix, and 8 others (fixed)
`str.removeprefix()` and `str.removesuffix()` (Python 3.9+) crashed
because no codegen handler existed. Also missing: `center`/`ljust`/
`rjust` with fill character, `isupper`, `islower`, `expandtabs`,
`partition`, `rpartition`.
Fix: Added C runtime implementations for all 10 methods and codegen
dispatch. Fill-character versions use separate `_fill` variants.
`partition`/`rpartition` return 3-element tuples (FpyList with
`is_tuple=1`).

### 42. Source merger didn't prefix from-import names (fixed)
`_prefix_module_defs` only prefixed FunctionDef, ClassDef, and Assign.
Names introduced by `from X import Y` were not prefixed, so dotted
access after merging (`module.func` → `module__func`) couldn't find
the imported names.
Fix: Added ImportFrom handling to `_prefix_module_defs` — each imported
name is added to `top_names`, and the import statement is rewritten
with `as` aliases (e.g. `from _foo import bar as prefix__bar`).

## Bugs fixed (2026-04-28, type dispatch & merger)

### 37. Invalid binop type combinations crashed with access violation (fixed)
`[1,2,3] + 5` caused an access violation instead of raising TypeError.
Root cause: (1) The compiler's slow-path binop handler passed native
container pointers (FpyList*, FpyDict*) to `cpython_binop` which expects
PyObject*. (2) The runtime `fastpy_fv_binop` had no guard before the
INT/BOOL arithmetic fallback — list pointers were treated as integers.
Fix: Added a compiler guard that routes native container types (list, dict,
set, tuple, str, bytes) through `fv_binop` instead of `cpython_binop`.
Added `list * int` / `int * list` repeat support to `fv_binop`. Added a
TypeError guard in `fv_binop` before the INT/BOOL fallback for any
remaining container+scalar combinations. Error message matches CPython:
`unsupported operand type(s) for +: 'list' and 'int'`.

### 38. Unknown-type parameters defaulted to int/str instead of runtime dispatch (fixed)
Functions called with forwarded or dynamically-typed arguments had their
parameters tagged as "str" (pointer) or "int" (non-pointer) even when
the actual type was unknown. This caused incorrect method dispatch (e.g.
`len(item)` on a list param tagged "str" would call `str_len`).
Root cause: Post-merge cleanup only cleared float+unknown conflicts, not
pointer+unknown. The parameter tag fallback only checked for multiple
conflicting types, not for the presence of unknown callers.
Fix: Extended post-merge cleanup to clear pointer-type param tags when
unknown callers exist. Extended the tag fallback to use "mixed" (runtime
dispatch via FpyValue tags) when any caller has an unknown argument type.

## Bugs fixed (2026-04-28, annotations & dispatch)

### 27. Type annotations ignored for codegen (fixed)
`def f(x: int) -> str` had no effect on code generation. All type inference
was structural (AST pattern matching on assignments).
Fix: Added always-on annotation reading for function parameters (no --typed
flag required). Reads container annotations (list[int], dict[str,int]),
scalar types (int, float, str, bool), bridge types (Path), module-qualified
types (pathlib.Path), and user class names. Sets the compile-time type tag
on FV-backed variables, enabling correct method dispatch for typed parameters.
Example: `def find_root(d: Path): return d.resolve()` now works because
`d` is tagged as "path", enabling `_is_path_expr` to recognize it.

### 28. `enumerate(..., start=N)` keyword argument ignored (fixed)
`for i, v in enumerate(lst, start=10)` started at 0 instead of 10.
Root cause: The inline enumerate optimization (`_emit_for_enumerate_inline`)
only checked positional args (`call.args`), not keyword args (`call.keywords`).
`start=10` is a keyword argument, not positional.
Fix: Added keyword argument scan for "start" in the inline enumerate emitter.

### 29. `MatchStar` pattern treated as never-match (fixed)
`case [first, *rest]:` silently failed to match. The MatchSequence handler
only supported exact-length matching, with no MatchStar support.
Fix: Enhanced MatchSequence to detect MatchStar sub-patterns. Uses
`>= min_length` instead of `== exact_length`. Matches prefix patterns from
the start, suffix patterns from the end, and creates a sub-list via
`list_slice` for the star capture variable.

### 30. `MatchMapping` pattern treated as never-match (fixed)
`case {"key": val}:` silently failed to match. No MatchMapping handler existed.
Fix: Added MatchMapping handler that checks tag==DICT, probes for each key
using `dict_get_fv_safe` (new function: returns NONE for missing keys without
raising KeyError), and recursively matches sub-patterns on the values.

### 31. Path attribute chaining crashed in FV context (fixed)
`p.parent.name` where `p: Path` crashed with access violation. The
intermediate `p.parent` result (a PyObject*) was caught by the generic
object attribute handler in `_load_or_wrap_fv`, which called `obj_get_fv`
on a PyObject* (expects FpyObj*).
Fix: Added path-expression early-exit in `_load_or_wrap_fv` before the
generic object handler — evaluates the full expression via `_emit_expr_value`
which correctly dispatches to path runtime functions.

### 32. MatchClass builtin type patterns caused refcount corruption (fixed)
`case int(n): / case str(s):` stored the capture variable unconditionally
even when the tag check failed. With compile-time type_tag "int", the
scalar-optimization path skipped rc_incref. At scope exit, rc_decref ran
on the runtime tag (e.g. STR for a string subject), freeing memory
without a matching incref → heap corruption (non-deterministic crashes).
Fix: Added conditional branch so variable binding only executes when the
tag check passes. Also use correct per-type compile-time tag ("str" for
str patterns, "float" for float, etc.).

### 33. MatchClass user-class patterns read slots on wrong class (fixed)
`case Point(x=x, y=y):` followed by `case Color(r=r, g=g, b=b):`
read Point's slot indices on a Color object when isinstance failed,
potentially corrupting refcounts for heap-typed attributes.
Fix: Added isinstance short-circuit — branch to fail_block immediately
on isinstance failure before any slot reads.

### 34. Return type annotations ignored (fixed)
`-> str` on function definitions had no effect on code generation. The
LLVM return type was set correctly from the annotation, but `ret_tag`
(the semantic type visible to call sites) was computed solely from
analyzing return statements in the function body.
Fix: After structural inference, override `ret_tag` from the return
annotation when present. Supports scalar types, containers, user
classes, None, and bridge types (pathlib.Path). Call sites now see
the annotated return type for correct dispatch (e.g., `.upper()` on
a `-> str` function's return value).

### 35. Unknown-type `+` on FpyValues corrupted string data (fixed)
`d["a"] + d["b"]` where both values are strings returned garbage
(string pointers bitcast to double). The UNKNOWN+UNKNOWN binop path
had no handler for string concatenation — it unconditionally converted
both operands to double and did float arithmetic.
Fix: Added runtime tag check in the UNKNOWN binop Add path. If both
FpyValue operands have tag STR, dispatch to str_concat. Otherwise
fall through to the numeric path.

### 36. Bridge dict mutation silently dropped (fixed)
Passing an FpyDict to a CPython function created a PyDict copy; in-place
mutations by the CPython function were discarded. List sync-back already
existed via `fpy_sync_pylist_to_fpylist`.
Fix: Implemented `fpy_sync_pydict_to_fpydict` — clears the FpyDict and
rebuilds from the mutated PyDict after every bridge call. Handles
add/modify/delete with proper rehashing on growth. Added to all bridge
call variants (1-arg through N-arg).

## Bugs fixed (2026-04-28, performance)

### 22. Implicit function returns leaked all FV-local variables (fixed)
Functions that fell off the end without an explicit `return` statement
never called `_emit_scope_decref()`. Every FV-local variable's refcount
was never decremented, causing permanent leaks. Over millions of calls,
accumulated objects made the GC scan O(n) objects per collection, with
collections triggered every 700 allocations — resulting in O(n²) total
GC time.
Fix: Added `_emit_scope_decref()` before all implicit return sites:
`_emit_function_def` (main functions), `_emit_method_body` (class
methods), and closure bodies. Mirrors the explicit `return` path in
`_emit_return` which already called it.

### 23. Temporary iterables in for-loops leaked (fixed)
`for x in make_list():` and `for k, v in enumerate(lst):` created
temporary FpyList* values for the iterable but never decremented them
after the loop ended. Named-variable iterables (`for x in my_list:`)
are borrowed references and don't need decref, but function-call results,
literals, and comprehensions are temporaries that must be freed.
Fix: Added `rc_decref` after the end block of `_emit_for_list`,
`_emit_for_tuple_unpack`, `_emit_for_string`, `_emit_for_dict` (always
for dict_keys() temporary), and `_emit_for_deque` (always for
deque_to_list() temporary).

### 24. `for i, val in enumerate(lst)` materialized N tuples (fixed)
`fastpy_enumerate()` allocated N 2-element lists (one per index-value
pair) up front, even though the loop immediately destructures them. For
N=130 in a tight loop called ~78K times (bm_spectral_norm), this created
10M+ temporary lists, causing massive allocation/GC overhead.
Fix: Added `_emit_for_enumerate_inline()` that detects `for i, val in
enumerate(lst)` and emits an inline indexed loop instead. Counter and
element are assigned directly from the list — zero tuple allocations.
Result: bm_spectral_norm 155s → 0.16s (now 11x faster than CPython).

### 25. GC threshold was fixed at 700, causing O(n²) collection (fixed)
The cycle collector ran a full scan of ALL tracked objects every 700
allocations. With 100K+ long-lived objects (bm_float_adapted: 100K Point
objects), each scan cost O(100K) and occurred ~143 times during object
creation, giving O(n²) total GC time.
Fix: Made the GC threshold adaptive — doubles when a collection finds
nothing to free (up to 50K cap), halves when objects are freed (down to
700 floor). Mirrors CPython's generational strategy without full
generational implementation.
Result: bm_float_adapted 212s → 1.9s.

### 26. In-place prefix reverse `a[:k+1] = a[k::-1]` allocated temp list (fixed)
The slice pattern `a[:k+1] = a[k::-1]` was compiled as: (1) call
`list_slice_step` to create a reversed copy (O(k) allocation), then (2)
call `list_slice_assign` to overwrite the prefix. The temporary reversed
list was also never freed (leaked on every iteration). In bm_fannkuch
with ~7M flip operations, this dominated runtime.
Fix: Added `_match_prefix_reverse()` AST pattern matcher that detects
the pattern. Added `fastpy_list_reverse_prefix()` runtime function that
reverses in place with O(k/2) swaps and zero allocations. The pattern is
detected BEFORE the RHS is evaluated, preventing the temp list from ever
being created.
Result: bm_fannkuch 440s → 8.3s.

## Bugs fixed (2026-04-28, self-hosting attempt)

### 17. C-extension wrapper modules merged incorrectly (fixed)
Stdlib modules like `ast`, `collections`, `json` that are thin wrappers
around C extensions (`from _ast import *`) were being source-merged by the
compiler. The merger's name prefixing turned `ast.Constant` into
`ast__Constant`, but since star-imported names couldn't be enumerated at
compile time, attribute access broke at runtime.
Fix: Added `_is_c_extension_wrapper()` to `stdlib_cache.py` — parses the
first ~50 statements and rejects any module with `from _<name> import *`.

### 18. Module-level from-imports invisible to user functions (fixed)
`from pathlib import Path` stored `Path` as a stack alloca in `fastpy_main`,
but user functions emitted in Pass 2 couldn't see it (functions are emitted
before `fastpy_main` runs in Pass 3).
Fix: Added "Pass 1.5" pre-scan that creates LLVM globals for all
module-level import names before function bodies are emitted.

### 19. Builtin names resolved as hash constants, not real objects (fixed)
`parser.add_argument("--python-version", type=str)` failed because `str` was
passed as `hash("str") & 0x7FFFFFFFFFFFFFFF` (an integer) instead of the
real Python `str` type object.
Fix: Added `fpy_cpython_get_builtin()` runtime function; changed
`_load_variable` for builtin names to return real PyObject*; fixed
`_bare_to_tag_data` to tag builtin names as OBJ instead of INT.

### 20. sys.argv empty in compiled binaries (fixed)
`main(void)` didn't pass argc/argv, so `sys.argv` was always empty and
`argparse` couldn't parse command-line arguments.
Fix: Changed to `main(int argc, char *argv[])` with global storage,
updated `fastpy_sys_argv()`, added `PySys_SetArgvEx` in CPython bridge init.

### 21. pathlib.Path as C strings caused segfaults on chained calls (fixed)
`Path("test.py").resolve().parent` segfaulted because native pathlib functions
returned C strings, but `.resolve()` results needed to be real Python objects
for further method calls.
Fix: Moved all pathlib functions from `runtime.c` to `cpython_bridge.c`.
`fastpy_path_new` now returns a real CPython `pathlib.Path` PyObject*.
Changed path VKind from STR to PYOBJ, fixed FV store to use OBJ tag,
moved path method dispatch before generic pyobj receiver check, added path
attribute handling to `_emit_attr_load`, added path exclusions in
`_is_pyobj_receiver` / `_infer_type_tag` / `_load_or_wrap_fv` to prevent
path variables from being hijacked by the generic bridge path.

## Bugs fixed (2026-04-22)

### 15. Runtime errors bypassed exception system (fixed)
27 error paths in `objects.c` used `fprintf(stderr, "Error: ...")+exit(1)`
instead of `fastpy_raise()`, making IndexError, KeyError, ValueError,
AttributeError, and ZeroDivisionError from runtime operations (list subscript,
dict lookup, method dispatch, complex/decimal division, deque ops, etc.)
uncatchable by try/except.
Fix: All 27 sites converted to `fastpy_raise()` with proper sentinel returns.
Added `FPY_EXC_ZERODIVISION` and `FPY_EXC_ATTRIBUTEERROR` constants to
`objects.c`. Formatted error messages use TLS `_err_buf[256]` for
AttributeError messages that include class/attribute names.

### 16. Traceback showed wrong line for non-top frames (fixed)
`fpy_shadow_push` recorded the function definition line for each frame.
When an exception propagated through nested calls, only the innermost frame
had the correct line; outer frames showed their definition lines.
Fix: `fpy_shadow_push` now freezes the caller frame's lineno from
`fpy_current_line` before pushing. `fpy_shadow_pop` restores
`fpy_current_line` from the now-current frame's saved lineno. This gives
every frame the exact call-site line.

### 9. Complex arithmetic print showed raw pointers (fixed)
`print(c1 + c2)` printed a raw i64 pointer instead of the complex result.
Root cause: `_wrap_for_print` had no handler for `inferred == "complex"` after
`_infer_type_tag` returned "complex" for BinOp with complex operands — the i64
(ptrtoint'd FpyComplex*) fell through to the scalar default, tagged as INT.
Fix: Added `inferred == "complex"` check in `_wrap_for_print`; extended
`_is_complex_expr` to handle BinOp and UnaryOp recursively; fixed USub to use
`complex_neg` instead of integer negation; fixed `abs()` to detect complex
expressions via `_is_complex_expr`; fixed `signbit()` check in C runtime for
`-0.0` real part (CPython prints `(-0-3j)` not `-3j`).

### 10. MatchSingleton treated as wildcard (fixed)
`case None:`, `case True:`, `case False:` matched everything.
Root cause: No handler for `ast.MatchSingleton` — fell through to the default
which returned None (always-match).
Fix: Added MatchSingleton handler checking FpyValue tag (NONE for None,
BOOL+data for True/False).

### 11. Match guard clause ignored on capture patterns (fixed)
`case n if n < 0:` always matched, ignoring the guard.
Root cause: Capture patterns returned `matched = None` (always match), and the
guard check only ran when `matched` was not None.
Fix: Restructured guard evaluation to always run when present.

### 12. Match sequence sub-pattern bug (fixed)
`case (0, y):` matched any sequence regardless of the literal.
Root cause: Sequence pattern matching only handled MatchAs (capture) sub-patterns;
MatchValue (literal) sub-patterns were ignored.
Fix: Recursive `_emit_match_pattern` for each element in the sequence.

### 13. Ellipsis printed as 0 (fixed)
`print(...)` and `x = ...; print(x)` both printed `0`.
Root cause: Ellipsis stored as i64(0) with no distinguishing tag.
Fix: Direct detection in print path (`_emit_print_single`, `_emit_write_single`)
for Ellipsis constants and variables tracked via `_ellipsis_vars`.

### 14. Positional-only params ignored (fixed)
`def f(a, b, /):` only saw 0 parameters; `a` and `b` were inaccessible.
Root cause: `node.args.posonlyargs` was never read — only `node.args.args`.
Fix: AST normalization at the top of `generate()` merges `posonlyargs` into
`args` before any codegen.

## Bugs fixed (2026-04-21)

### 1. Linked list None traversal (fixed)
`while cur is not None: cur = cur.next` crashed when `cur.next` held None.
Root cause: obj attribute slot containing None was loaded without preserving
the FPY_TAG_NONE tag, so the `is not None` check saw an integer 0 (tagged
INT) instead of None.
Fix: FV-aware attribute load path in `_emit_is_compare` and `_load_or_wrap_fv`
preserves runtime tag for obj attributes that may hold None.

### 2. Set union returned wrong size (fixed)
`{1,2,3} | {4,5,6}` returned len=1 instead of len=6.
Root cause: `_infer_type_tag` had no handler for set operations (BitOr, BitAnd,
etc.), so the result was tagged "int" instead of "set", causing `len()` to
dispatch through the wrong path.
Fix: Added set operation detection to `_infer_type_tag`.

### 3. Mixed-type dict values from json.loads (fixed)
`parsed["x"]` on a `json.loads()` result returned string representation
instead of actual values for nested lists/dicts.
Root cause: dict subscript for unknown value types called `fv_str` (string
format) instead of returning the raw FpyValue data.
Fix: Return raw data from dict subscript for unknown value types; let the
FV-aware print/assignment path handle type dispatch.

### 4. Cross-function list parameter (fixed)
Passing a list returned from one function as a parameter to another function
wasn't typed correctly — the parameter was i64 instead of i8*.
Root cause: call-site analysis didn't propagate function return types to
variable type tracking.
Fix: Added return-type propagation in `_analyze_call_sites` — traces
through `data = make_list()` to infer `data` is a list.

### 5. SafeIRBuilder LLVM type mismatches (fixed)
Various LLVM type mismatches (i64 vs i8*, i32 vs i64, etc.) caused crashes
in call, icmp, fadd, store, ret, phi, and select instructions.
Fix: SafeIRBuilder wrapper auto-coerces all LLVM type mismatches at every
IR instruction emission point.

### 6. Exception handling noinline fix (fixed)
Functions containing `raise` statements caused LLVM optimization issues.
Fix: Functions that contain raise statements are now marked `noinline` to
prevent the optimizer from mishandling exception control flow.

### 7. ABI version check at startup (fixed)
Compiled binaries would silently crash if run with a different Python version
than they were compiled against.
Fix: Added compile-time vs runtime Python version ABI check at startup,
with a clear error message on mismatch.

### 8. Function return type propagation (fixed)
List-of-lists returned from functions lost their element type information.
Fix: Added list-of-lists detection from append patterns, propagating
nested list types through function return boundaries.

## Grammar gaps (Python 3.14)

Systematic comparison against the Python 3.14 PEG grammar (`Grammar/python.gram`).

### Formerly silently wrong, now implemented
- **`type` statement** (Python 3.12+) — `type X = int | str` silently ignored
  (no runtime effect). Tested.
- **`@` operator** (MatMult) — `a @ b` dispatches to `__matmul__` on user
  classes. Correctly handles both int-returning and object-returning methods.
  Tested with dot product and matrix multiplication.
- **t-strings** (Python 3.14) — `t"hello {name}"` compiled as f-string
  (string interpolation). Note: CPython 3.14 returns `Template` objects;
  fastpy returns plain strings. This is a semantic simplification.

### Tested (2026-04-22)
- **match/case** — literal, string, capture, wildcard, or, guard, sequence,
  nested sequence, singleton (None/True/False), mixed singleton+literal
- **except\*** — exception groups (single/multiple handlers, plain exceptions)
- **Complex numbers** — arithmetic (+, -, *), abs(), unary negation, repr
- **Bytes literals** — `b"hello"` (partial: latin-1 decode)
- **Ellipsis** — `print(...)` and `x = ...; print(x)` both print "Ellipsis"
- **for/while ... else:** — with and without break
- **Positional-only params** — `def f(a, /, b):` works correctly
- **Per-variable overflow control** — `Annotated[int, Unchecked/Checked]` and
  `unchecked_int()/checked_int()` for 64-bit; `Unchecked32/Checked32` and
  `unchecked_int32()/checked_int32()` for 32-bit. Tested: happy path, wrapping
  overflow, OverflowError, augmented assignment, functions, annotated params

### Implemented (2026-04-22)
- **Shadow call stack** — runtime tracebacks for unhandled exceptions showing
  `File "source.py", line N, in func` for each frame. Push/pop at function
  entry/exit; line number tracked via global store updated per-statement.
  Per-frame line accuracy: push freezes caller's line from the compiler-updated
  global, pop restores it — every frame shows the exact call-site line, not
  the function definition line. Argument values displayed inline:
  `func(name='key', index=99)` with type-aware formatting (int, float, str,
  bool, None, list/dict/obj placeholders).
- **Runtime exceptions are catchable** — all `fprintf+exit` error paths in
  `objects.c` (27 sites: IndexError, KeyError, ValueError, AttributeError,
  ZeroDivisionError) converted to `fastpy_raise()` with sentinel returns.
  Exceptions propagate through the polling model and are catchable by
  try/except. Tested in all three threading modes (none, GIL, free-threaded).
- **CPython-quality syntax errors** — `traceback.format_exception_only()` for
  source line, caret, and column position in compile-time errors.
- **C extension for Int32/UInt32/Int64/UInt64** — `fastpy/_fastints.c` replaces
  pure-Python `ints.py` for CPython-side fixed-width integer performance.
  Falls back to pure Python if the extension is not compiled.
- **Native `weakref` module** — `weakref.ref(obj)` and `_weakref.ref(obj)` create
  native weak references (FpyWeakRef). Calling the weakref dereferences it,
  returning the target object or None if the target has been collected. Each
  FpyObj carries a `weakref_list` linked list; all weakrefs are invalidated
  (target set to NULL) when the object is destroyed.

## Known limitations (not bugs)

### Type system

- **No interprocedural type inference without annotations** — When a Path,
  PyObject*, or other typed value is passed as a function argument *without*
  a type annotation, the callee sees it as an untyped FpyValue. Method calls
  on the parameter (e.g. `source_dir.resolve()`) cannot dispatch to native
  handlers.
  **Partially fixed:** Adding `d: Path` annotations now works (see bug 27).
  Call-site analysis now propagates `path`/`pyobj` tags through function
  arguments, and the FV dispatch fallback routes path/pyobj-tagged receivers
  through `fpy_fv_call_method` (CPython bridge). For native types (str, list,
  dict), the existing type-specific handlers catch them correctly.
  **Remaining gap fixed:** When call-site analysis can't determine an
  argument's type (e.g., the argument is itself an untyped variable), the
  post-merge cleanup now clears pointer-type param tags that have unknown
  callers, and the parameter tag fallback uses "mixed" (runtime dispatch)
  instead of defaulting to "str"/"int". This ensures functions called
  with forwarded or dynamically-typed arguments dispatch correctly.
  **Cross-category conflicts fixed:** Same function called with both int
  and str (or int+list, str+int+list, etc.) now correctly uses "mixed" tag
  with runtime dispatch. Both the pointer branch (formerly defaulted to
  "str") and non-pointer branch (formerly defaulted to "int") now detect
  conflicting types via `_function_signatures` and set tag="mixed".
  Same-category pointer conflicts (str+list, str+dict, etc.) also work
  via "mixed" tag with runtime dispatch through `fastpy_fv_len` and
  `fastpy_fv_print`.

- **BigInt through function calls** *(fixed)* — BigInt values passed through
  function parameters now work correctly. Fixes: BigInt param types use i8_ptr
  (pointer), BigInt fast paths in `_emit_binop` and `_emit_compare`, BinOp
  constant-fold detection for expressions like `10**20`, `_type_cat` treats
  bigint as numeric ("I") for merge compatibility with int, and runtime
  INT→BigInt promotion in `_unwrap_fv_for_tag` handles mixed int/bigint
  callers. See bugs fixed section.

- **Return type annotations ignored** *(fixed)* — `-> str` on function
  definitions now propagates to `ret_tag`, so call sites see the correct
  type. Supports scalar types (int, float, str, bool), containers
  (list, dict, set, tuple), user classes, None, and bridge types (Path).
  See bug 34.

- **Mixed-type dict value access** *(fixed)* — Dict values from dynamic
  sources (json.loads) and mixed-value literal dicts now preserve runtime
  tags through nested subscript access. `addr = data["address"]` stores a
  full FpyValue with runtime tag; `addr["city"]` dispatches through
  `fastpy_fv_subscript` which checks the tag at runtime (dict→dict_get_fv,
  list→list_get_fv, str→str_index). Also fixed: `_infer_type_tag` now
  checks per-key types for literal dicts, so `d["address"]` where the
  compiler tracked `"address" → dict` correctly tags the variable.

### Object model

- **Fastpy objects are not PyObjects** *(largely fixed)* — The mirror object
  pattern is implemented via `FpyObjProxyType`, `FpyNativeCallableType`,
  `FpyClosureProxyType`, and `FpyBoundMethodProxyType` in `cpython_bridge.c`.
  Native objects, functions, lambdas, and closures are automatically wrapped
  as PyObject* when passed to CPython APIs. Tested working:
  `functools.reduce(lambda ...)`, `map(lambda ...)`, `filter(lambda ...)`,
  `sorted(key=lambda ...)`, `collections.defaultdict(int)`, passing class
  instances to CPython functions. Round-trip unwrapping preserves identity
  (`pyobject_to_fpy` detects FpyObjProxy and unwraps to original FpyObj*).
  `defaultdict(list)` now works correctly: factory type tracking
  (`_defaultdict_var_factories`) lets `_is_list_expr` and `_infer_type_tag`
  recognize `d["key"]` as a list when `d = defaultdict(list)`, enabling
  native `.append()`, `len()`, and print dispatch.

- **PyObject* values in FpyValue OBJ tag are not FpyObj** *(fixed)* —
  CPython PyObject* (e.g. `pathlib.Path`) stored in FpyValue with OBJ tag.
  All runtime paths now check `FPY_OBJ_MAGIC` to distinguish native FpyObj*
  from CPython PyObject*: `fastpy_obj_write`, `fpy_value_repr`,
  `fpy_rc_incref/decref`, `fastpy_fv_truthy` (delegates to `PyObject_IsTrue`),
  and `fpy_value_compare` (delegates to `fpy_cpython_compare` for rich
  comparison). Multi-arg print, truthiness, and comparison all work correctly
  for both native objects and CPython PyObject* values.

### Bridge

- **Bridge dict mutation silently dropped** *(fixed)* — Passing an FpyDict to
  a CPython function now syncs mutations back. `fpy_sync_pydict_to_fpydict`
  clears and rebuilds the FpyDict from the mutated PyDict after every bridge
  call. Handles add/modify/delete, rehashes index table on growth. Added to
  all call variants (1-arg, 2-arg, 3-arg, N-arg) alongside existing list
  sync-back. See bug 36.

### Source merger

- **Packages can now be merged** *(fixed)* — Stdlib packages with
  `__init__.py` are now supported. Self-contained packages (no submodule
  imports) are merged directly as single files. Packages with simple
  submodule imports are also supported — the recursive merger resolves
  relative imports within package directories and merges submodules with
  appropriate prefixing. Dotted module names (`from html.entities import
  name2codepoint`) are also resolved to the correct submodule file.
  **Tested working:** `html.escape`, `html.entities` name lookups.
  **Limitation:** Many stdlib packages use advanced Python features
  (metaclasses, complex enums, regex) that the AOT compiler can't handle
  yet, so the merge succeeds but the compiled binary crashes. These
  modules fall back to the CPython bridge.

- **C-extension wrapper modules rejected** — Stdlib modules whose public
  API comes from `from _foo import *` (e.g. `ast`, `collections`, `json`,
  `operator`, `functools`) cannot be source-merged. Star-imported names
  ARE enumerable at compile time (via `__import__` + `__all__`/`dir()`),
  and `_expand_star_imports()` in `stdlib_cache.py` can expand them to
  explicit imports. However, the codegen can't call CPython bridge
  functions stored in variables — `pack = _struct.pack; pack('i', 42)`
  crashes because the codegen treats the variable as a native function
  reference, not a PyObject* callable. Until `from X import Y` for C
  extension builtins (or calling PyObject* through variables) is fixed
  in codegen, these modules stay on the CPython bridge import path.
  Detected by `_is_c_extension_wrapper()` in `stdlib_cache.py`.

### Self-hosting status (2026-04-28)

Attempted to compile the fastpy compiler with itself. Current status:
**partially working** — basic compilation pipeline steps execute but
full self-hosting fails due to the limitations above.

**What works in the self-compiled binary:**
- `from pathlib import Path` → Path objects as real CPython PyObject*
- `Path("file.py").read_text()` → reads file contents correctly
- `Path("file.py").resolve().parent` → chained path operations
- `Path("file.py").name`, `.stem`, `.suffix` → string properties
- `from compiler.pipeline import compile_source` → module import via merger
- `sys.argv` propagation to compiled binaries
- Builtin names (`str`, `int`, `Exception`, etc.) as real PyObject* values

**What blocks full self-hosting:**
- Functions that receive Path/PyObject* parameters *whose type cannot be
  inferred from call-site analysis* still fail to dispatch methods.
  Call-site analysis now handles `Path(...)` constructor calls and
  path/pyobj-tagged variables as arguments, but deeply nested or dynamic
  dispatch chains remain unresolved.
- The pipeline functions use extensive dynamic typing (dicts of mixed types,
  AST node manipulation, `isinstance` checks) that requires the CPython
  bridge for every operation on untyped parameters.
