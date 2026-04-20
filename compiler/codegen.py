"""
LLVM IR code generation for fastpy.

Takes a Python AST and generates LLVM IR that calls into the fastpy
C runtime. The generated IR defines a `fastpy_main()` function that
the runtime's `main()` calls.

Milestone 1: print() with literal arguments (int, float, str, bool, None).
Milestone 2: variables, assignment, multi-statement programs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

import llvmlite.ir as ir


# LLVM type aliases
i8 = ir.IntType(8)
i32 = ir.IntType(32)
i64 = ir.IntType(64)
double = ir.DoubleType()
void = ir.VoidType()
i8_ptr = ir.PointerType(i8)

# Tagged value: mirrors C FpyValue struct { int tag; union { i64 i; double f; char* s; int b; FpyList* list; FpyObj* obj; } data; }
# The union is 8 bytes on 64-bit; the tag is 4 bytes plus 4 bytes padding.
# LLVM literal struct {i32, i64} — LLVM handles alignment; on most ABIs this
# is passed/returned by value in registers (or by hidden pointer for MSVC x64).
fpy_val = ir.LiteralStructType([i32, i64])
fpy_val_ptr = ir.PointerType(fpy_val)

# FpyObj layout — must match struct FpyObj in objects.h:
#   int class_id;                       (4 bytes + 4 padding)
#   FpyValue *slots;                    (8-byte pointer)
#   FpyObjAttrs *dynamic_attrs;         (8-byte pointer, NULL unless used)
# Post-Phase-21: dynamic attr storage moved out-of-line into a heap
# side-table so FpyObj is ~24 bytes (was ~1560). Used for direct-struct
# IR access to obj->slots[idx] (skips the fastpy_obj_get_slot /
# fastpy_obj_set_slot function call overhead).
# FpyObj layout on x64:
#   offset  0: i32 refcount
#   offset  4: (padding)
#   offset  8: FpyGCNode (24 bytes: 2 ptrs + 2 i32s)
#   offset 32: i32 magic
#   offset 36: i32 class_id
#   offset 40: ptr slots
#   offset 48: ptr dynamic_attrs
# Represent GC node as 3 opaque i64s to match alignment:
fpy_obj_type = ir.LiteralStructType([
    i64,                             # refcount (i32) + padding (4 bytes) = 8
    i64,                             # gc_node.gc_prev
    i64,                             # gc_node.gc_next
    i64,                             # gc_node.gc_refs (i32) + gc_node.gc_flags (i32)
    i64,                             # magic (i32) + class_id (i32)
    fpy_val_ptr,                     # slots
    i8_ptr,                          # dynamic_attrs (opaque to codegen)
])
fpy_obj_ptr = ir.PointerType(fpy_obj_type)

# Tag constants — MUST match the C #defines in objects.h
FPY_TAG_INT = 0
FPY_TAG_FLOAT = 1
FPY_TAG_STR = 2
FPY_TAG_BOOL = 3
FPY_TAG_NONE = 4
FPY_TAG_LIST = 5
FPY_TAG_OBJ = 6
FPY_TAG_DICT = 7
FPY_TAG_BYTES = 8
FPY_TAG_SET = 9


@dataclass
class FuncInfo:
    """Metadata about a user-defined function."""
    func: ir.Function          # LLVM function
    ret_tag: str               # "int", "float", "void"
    param_count: int           # total parameter count
    defaults: list[ast.expr]   # AST nodes for default values (right-aligned)
    min_args: int              # minimum positional args = param_count - len(defaults)
    is_vararg: bool = False    # True if function uses *args
    is_kwarg: bool = False     # True if function uses **kwargs
    # Post-refactor: LLVM signature is all FpyValue. These hold the *static*
    # types the body expects each param to have, used for unwrap-at-entry.
    # None means "don't convert — pass FpyValue through" (future full polymorphism).
    static_param_types: list = None  # list[ir.Type]
    static_ret_type: object = None   # ir.Type (the bare type the body produces)
    # If True, this function was declared with the post-refactor FpyValue ABI.
    # During migration, some functions (lambdas, vararg) stay on the old ABI.
    uses_fv_abi: bool = False
    # True if any return path yields None (return None / bare return).
    # Used to decide whether the call site should preserve the raw FpyValue
    # (to keep the NONE tag) rather than unwrapping to a bare LLVM value.
    may_return_none: bool = False


@dataclass
class ClassInfo:
    """Metadata about a user-defined class."""
    name: str
    class_id_global: ir.GlobalVariable  # LLVM global holding the runtime class_id
    methods: dict[str, ir.Function]     # method_name -> LLVM function
    parent_name: str | None             # parent class name or None
    init_arg_count: int                 # number of __init__ args (excluding self)
    init_defaults: list = None          # AST nodes for __init__ default values (right-aligned)
    method_asts: dict = None            # method_name -> ast.FunctionDef for return-type inference
    classmethods: set = None            # set of method names marked @classmethod
    staticmethods: set = None           # set of method names marked @staticmethod
    properties: set = None              # set of method names marked @property

# Type tag constants for our tagged value system (future use)
TAG_INT = 0
TAG_FLOAT = 1
TAG_STR = 2
TAG_BOOL = 3
TAG_NONE = 4


class CodeGen:
    """Generates LLVM IR from a Python AST."""

    def __init__(self, threading_mode: int = 0) -> None:
        self.module = ir.Module(name="fastpy_module")
        self.module.triple = "x86_64-pc-windows-msvc"
        # Explicit data layout for x86_64 Windows MSVC. Matters for correct
        # struct layout (padding/alignment) when we emit direct GEP access
        # into structs like FpyObj/FpyValue.
        self.module.data_layout = (
            "e-m:w-p270:32:32-p271:32:32-p272:64:64"
            "-i64:64-f80:128-n8:16:32:64-S128"
        )
        self._threading_mode = threading_mode

        # Declare runtime functions
        self._declare_runtime_functions()

        # Emit threading mode global — overrides the weak default in threading.c.
        # Use no explicit linkage (default = external definition with init).
        gvar = ir.GlobalVariable(self.module, i32,
                                 name="fpy_threading_mode")
        gvar.initializer = ir.Constant(i32, threading_mode)

        # String constant counter
        self._str_counter = 0

        # Reference counting: emit incref/decref at variable stores and scope exits.
        # Disabled by default until the full GC is ready; enable for testing.
        self._USE_REFCOUNT = True

        # Counter for unique block names
        self._block_counter = 0

        # Per-function state (saved/restored when entering nested functions)
        self.function: ir.Function | None = None
        self.builder: ir.IRBuilder | None = None
        self.variables: dict[str, tuple[ir.AllocaInstr, str]] = {}
        self._loop_stack: list[tuple[ir.Block, ir.Block]] = []
        self._in_try_block: bool = False
        # Stack of finally-body AST lists currently enclosing the emitter.
        # A `return` inside a try-with-finally must emit all pending finally
        # bodies in LIFO order before actually returning.
        self._finally_stack: list[list[ast.stmt]] = []

        # Generator functions: set of function names that contain yield
        self._generator_funcs: set[str] = set()

        # CPython module imports: module_name -> LLVM global (i8* PyObject*)
        self._cpython_modules: dict[str, ir.GlobalVariable] = {}

        # User-defined functions: name -> FuncInfo
        self._user_functions: dict[str, FuncInfo] = {}

        # User-defined classes: name -> ClassInfo
        self._user_classes: dict[str, ClassInfo] = {}

        # Global variables: name -> (global_var, type_tag)
        # Module-level vars that functions can access via 'global' keyword
        self._global_vars: dict[str, tuple[ir.GlobalVariable, str]] = {}

        # Pre-scanned list element types from append() analysis
        # Maps variable name -> inferred element type (e.g. "list", "str", "obj")
        self._list_append_types: dict[str, str] = {}

        # Current class name while emitting class method bodies (for super() lookup)
        self._current_class: str | None = None

        # Per-class container attribute detection:
        # Maps class name -> (list_attrs, dict_attrs)
        self._class_container_attrs: dict[str, tuple[set[str], set[str]]] = {}

        # Per-class float/string/bool attribute detection (including inherited attrs)
        self._per_class_float_attrs: dict[str, set[str]] = {}
        self._per_class_string_attrs: dict[str, set[str]] = {}
        self._per_class_bool_attrs: dict[str, set[str]] = {}

        # Class-level constant attributes: class_name -> {attr: ast.Constant}
        self._class_const_attrs: dict[str, dict[str, ast.expr]] = {}

        # Track variable -> class name for object-typed variables
        self._obj_var_class: dict[str, str] = {}

        # Track dict variables whose values are all lists (so d[k] returns a list)
        self._dict_var_list_values: set[str] = set()

        # Track dict variables whose values are all dicts (so d[k] returns a dict)
        self._dict_var_dict_values: set[str] = set()

        # Track dict variables whose values are all ints (so d[k] returns an int)
        self._dict_var_int_values: set[str] = set()
        # Track dict variables whose values are all class instances
        # (so d[k] returns an obj pointer, not a string-representation).
        self._dict_var_obj_values: set[str] = set()
        # Per-key value types for mixed-value dicts: maps variable name to
        # a dict of {key_str: type_tag}. Enables `d["age"]` to return int
        # even when the dict also contains string-valued keys. Populated
        # for module/function-scope dicts whose values have known types
        # per key, either directly (literals) or via propagation from a
        # list-of-dicts loop variable.
        self._dict_var_key_types: dict[str, dict[str, str]] = {}

        # Track tuple variable element types for subscript dispatch
        self._tuple_elem_types: dict[str, str] = {}

        # Per-class object attribute types: class_name -> attr -> nested_class_name.
        # E.g., Entity.pos holds a Position → _class_obj_attr_types["Entity"]["pos"] = "Position"
        self._class_obj_attr_types: dict[str, dict[str, str]] = {}

        # Per-class static attribute slots: class_name -> {attr: slot_index}.
        # Built by scanning all methods for self.attr and obj.attr patterns.
        # Inherited attrs keep the parent's slot index (child slots start after).
        self._class_attr_slots: dict[str, dict[str, int]] = {}

    def _declare_runtime_functions(self) -> None:
        """Declare external runtime functions we can call."""
        self.runtime = {}

        # void fastpy_print_newline(void)
        ft = ir.FunctionType(void, [])
        self.runtime["print_newline"] = ir.Function(self.module, ft, name="fastpy_print_newline")

        # FpyValue operations — the print/write dispatch is now done via these,
        # replacing the old typed variants (print_int/float/str/bool/none,
        # list_print, tuple_print, dict_print, obj_print, and their write_*
        # counterparts). All print/write goes through fv_print / fv_write.
        ft = ir.FunctionType(void, [i32, i64])
        self.runtime["fv_print"] = ir.Function(self.module, ft, name="fastpy_fv_print")
        self.runtime["fv_write"] = ir.Function(self.module, ft, name="fastpy_fv_write")
        ft = ir.FunctionType(i8_ptr, [i32, i64])
        self.runtime["fv_repr"] = ir.Function(self.module, ft, name="fastpy_fv_repr")
        self.runtime["fv_str"] = ir.Function(self.module, ft, name="fastpy_fv_str")
        ft = ir.FunctionType(i32, [i32, i64])
        self.runtime["fv_truthy"] = ir.Function(self.module, ft, name="fastpy_fv_truthy")

        # int64_t fastpy_pow_int(int64_t base, int64_t exp)
        ft = ir.FunctionType(i64, [i64, i64])
        self.runtime["pow_int"] = ir.Function(self.module, ft, name="fastpy_pow_int")
        ft = ir.FunctionType(i64, [i64, i64, i64])
        self.runtime["pow_mod"] = ir.Function(self.module, ft, name="fastpy_pow_mod")

        # double fastpy_pow_float(double base, double exp)
        ft = ir.FunctionType(double, [double, double])
        self.runtime["pow_float"] = ir.Function(self.module, ft, name="fastpy_pow_float")

        # String operations
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["str_concat"] = ir.Function(self.module, ft, name="fastpy_str_concat")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["str_len"] = ir.Function(self.module, ft, name="fastpy_str_len")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64])
        self.runtime["str_index"] = ir.Function(self.module, ft, name="fastpy_str_index")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64, i64, i64, i64])
        self.runtime["str_slice"] = ir.Function(self.module, ft, name="fastpy_str_slice")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64, i64, i64, i64, i64])
        self.runtime["str_slice_step"] = ir.Function(self.module, ft, name="fastpy_str_slice_step")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64])
        self.runtime["str_repeat"] = ir.Function(self.module, ft, name="fastpy_str_repeat")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["str_lower"] = ir.Function(self.module, ft, name="fastpy_str_lower")
        ft = ir.FunctionType(i8_ptr, [i64])
        self.runtime["int_to_str"] = ir.Function(self.module, ft, name="fastpy_int_to_str")
        ft = ir.FunctionType(i8_ptr, [double])
        self.runtime["float_to_str"] = ir.Function(self.module, ft, name="fastpy_float_to_str")

        # List operations (lists are opaque pointers = i8*)
        ft = ir.FunctionType(i8_ptr, [])
        self.runtime["list_new"] = ir.Function(self.module, ft, name="fastpy_list_new")
        # FV-ABI list element operations (Phase 4 of tagged-value refactor).
        # The old typed variants (list_append_int/float/str/bool/none/list,
        # list_set_int/str) are superseded by the FV versions and removed.
        ft = ir.FunctionType(void, [i8_ptr, i32, i64])
        self.runtime["list_append_fv"] = ir.Function(self.module, ft, name="fastpy_list_append_fv")
        ft = ir.FunctionType(void, [i8_ptr, i64, ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["list_get_fv"] = ir.Function(self.module, ft, name="fastpy_list_get_fv")
        ft = ir.FunctionType(void, [i8_ptr, i64, i32, i64])
        self.runtime["list_set_fv"] = ir.Function(self.module, ft, name="fastpy_list_set_fv")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr, i32, i64])
        self.runtime["dict_set_fv"] = ir.Function(self.module, ft, name="fastpy_dict_set_fv")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr, ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["dict_get_fv"] = ir.Function(self.module, ft, name="fastpy_dict_get_fv")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["list_length"] = ir.Function(self.module, ft, name="fastpy_list_length")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["list_to_str"] = ir.Function(self.module, ft, name="fastpy_list_to_str")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["list_sorted"] = ir.Function(self.module, ft, name="fastpy_list_sorted")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["list_reversed"] = ir.Function(self.module, ft, name="fastpy_list_reversed")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["list_set"] = ir.Function(self.module, ft, name="fastpy_list_set")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["set_union"] = ir.Function(self.module, ft, name="fastpy_set_union")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["set_intersection"] = ir.Function(self.module, ft, name="fastpy_set_intersection")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["set_difference"] = ir.Function(self.module, ft, name="fastpy_set_difference")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["set_symmetric_diff"] = ir.Function(self.module, ft, name="fastpy_set_symmetric_diff")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])  # str_split(s) -> list
        self.runtime["str_split"] = ir.Function(self.module, ft, name="fastpy_str_split")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])
        self.runtime["str_compare"] = ir.Function(self.module, ft, name="fastpy_str_compare")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["str_upper"] = ir.Function(self.module, ft, name="fastpy_str_upper")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr, i8_ptr])
        self.runtime["str_replace"] = ir.Function(self.module, ft, name="fastpy_str_replace")
        ft = ir.FunctionType(i32, [i8_ptr, i8_ptr])
        self.runtime["str_startswith"] = ir.Function(self.module, ft, name="fastpy_str_startswith")
        ft = ir.FunctionType(i32, [i8_ptr, i8_ptr])
        self.runtime["str_endswith"] = ir.Function(self.module, ft, name="fastpy_str_endswith")
        ft = ir.FunctionType(i32, [i8_ptr, i8_ptr])
        self.runtime["str_contains"] = ir.Function(self.module, ft, name="fastpy_str_contains")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["str_strip"] = ir.Function(self.module, ft, name="fastpy_str_strip")
        self.runtime["str_lstrip"] = ir.Function(self.module, ft, name="fastpy_str_lstrip")
        self.runtime["str_rstrip"] = ir.Function(self.module, ft, name="fastpy_str_rstrip")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["str_strip_chars"] = ir.Function(self.module, ft, name="fastpy_str_strip_chars")
        ft = ir.FunctionType(i32, [i8_ptr])
        self.runtime["str_isdigit"] = ir.Function(self.module, ft, name="fastpy_str_isdigit")
        self.runtime["str_isalpha"] = ir.Function(self.module, ft, name="fastpy_str_isalpha")
        self.runtime["str_isalnum"] = ir.Function(self.module, ft, name="fastpy_str_isalnum")
        self.runtime["str_isspace"] = ir.Function(self.module, ft, name="fastpy_str_isspace")
        ft = ir.FunctionType(i8_ptr, [i64])
        self.runtime["chr"] = ir.Function(self.module, ft, name="fastpy_chr")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["ord"] = ir.Function(self.module, ft, name="fastpy_ord")
        self.runtime["str_to_int"] = ir.Function(self.module, ft, name="fastpy_str_to_int")
        ft = ir.FunctionType(double, [i8_ptr])
        self.runtime["str_to_float"] = ir.Function(self.module, ft, name="fastpy_str_to_float")
        ft = ir.FunctionType(i8_ptr, [i64])
        self.runtime["hex"] = ir.Function(self.module, ft, name="fastpy_hex")
        self.runtime["oct"] = ir.Function(self.module, ft, name="fastpy_oct")
        self.runtime["bin"] = ir.Function(self.module, ft, name="fastpy_bin")
        ft = ir.FunctionType(i64, [double])
        self.runtime["round"] = ir.Function(self.module, ft, name="fastpy_round")
        ft = ir.FunctionType(double, [double, i64])
        self.runtime["round_ndigits"] = ir.Function(self.module, ft, name="fastpy_round_ndigits")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["str_repr"] = ir.Function(self.module, ft, name="fastpy_str_repr")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["str_format_percent"] = ir.Function(self.module, ft, name="fastpy_str_format_percent")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr])
        self.runtime["dict_update"] = ir.Function(self.module, ft, name="fastpy_dict_update")

        # More string methods
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["str_capitalize"] = ir.Function(self.module, ft, name="fastpy_str_capitalize")
        self.runtime["str_title"] = ir.Function(self.module, ft, name="fastpy_str_title")
        self.runtime["str_swapcase"] = ir.Function(self.module, ft, name="fastpy_str_swapcase")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64])
        self.runtime["str_center"] = ir.Function(self.module, ft, name="fastpy_str_center")
        self.runtime["str_ljust"] = ir.Function(self.module, ft, name="fastpy_str_ljust")
        self.runtime["str_rjust"] = ir.Function(self.module, ft, name="fastpy_str_rjust")
        self.runtime["str_zfill"] = ir.Function(self.module, ft, name="fastpy_str_zfill")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["str_splitlines"] = ir.Function(self.module, ft, name="fastpy_str_splitlines")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr, i64])
        self.runtime["str_split_max"] = ir.Function(self.module, ft, name="fastpy_str_split_max")

        # List methods
        ft = ir.FunctionType(void, [i8_ptr, i64])
        self.runtime["list_remove"] = ir.Function(self.module, ft, name="fastpy_list_remove")
        self.runtime["list_delete_at"] = ir.Function(self.module, ft, name="fastpy_list_delete_at")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr])
        self.runtime["dict_delete"] = ir.Function(self.module, ft, name="fastpy_dict_delete")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr])
        self.runtime["list_remove_str"] = ir.Function(self.module, ft, name="fastpy_list_remove_str")
        ft = ir.FunctionType(void, [i8_ptr, i64, i64])
        self.runtime["list_insert_int"] = ir.Function(self.module, ft, name="fastpy_list_insert_int")
        ft = ir.FunctionType(void, [i8_ptr, i64, i8_ptr])
        self.runtime["list_insert_str"] = ir.Function(self.module, ft, name="fastpy_list_insert_str")
        # list.copy() -> new list, list.clear() -> void
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["list_copy"] = ir.Function(self.module, ft, name="fastpy_list_copy")
        ft = ir.FunctionType(void, [i8_ptr])
        self.runtime["list_clear"] = ir.Function(self.module, ft, name="fastpy_list_clear")
        # list slice assign: list_slice_assign(list, start, stop, new_values)
        ft = ir.FunctionType(void, [i8_ptr, i64, i64, i8_ptr])
        self.runtime["list_slice_assign"] = ir.Function(self.module, ft, name="fastpy_list_slice_assign")
        # Dict-backed set operations
        ft = ir.FunctionType(i8_ptr, [i8_ptr])  # set_from_list(list) -> set(dict)
        self.runtime["set_from_list"] = ir.Function(self.module, ft, name="fastpy_set_from_list")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])  # set_to_list(set) -> list
        self.runtime["set_to_list"] = ir.Function(self.module, ft, name="fastpy_set_to_list")
        ft = ir.FunctionType(void, [i8_ptr, i32, i64])  # set_add_fv(set, tag, data)
        self.runtime["set_add_fv"] = ir.Function(self.module, ft, name="fastpy_set_add_fv")
        ft = ir.FunctionType(void, [i8_ptr, i32, i64])  # set_discard_fv(set, tag, data)
        self.runtime["set_discard_fv"] = ir.Function(self.module, ft, name="fastpy_set_discard_fv")
        ft = ir.FunctionType(i32, [i8_ptr, i32, i64])  # set_contains_fv(set, tag, data) -> bool
        self.runtime["set_contains_fv"] = ir.Function(self.module, ft, name="fastpy_set_contains_fv")
        # Raw CPython call variants: return PyObject* directly (for pyobj storage)
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["cpython_call0_raw"] = ir.Function(self.module, ft, name="fpy_cpython_call0_raw")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i32, i64])
        self.runtime["cpython_call1_raw"] = ir.Function(self.module, ft, name="fpy_cpython_call1_raw")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i32, i64, i32, i64])
        self.runtime["cpython_call2_raw"] = ir.Function(self.module, ft, name="fpy_cpython_call2_raw")
        # Wrap a native function pointer as a CPython callable
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["cpython_wrap_native"] = ir.Function(self.module, ft, name="fpy_cpython_wrap_native")

        # Native math functions (C's libm) — avoids CPython bridge for math
        ft_dd = ir.FunctionType(double, [double])
        ft_dd2 = ir.FunctionType(double, [double, double])
        for name in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan",
                      "exp", "log", "log10", "ceil", "floor", "fabs",
                      "sinh", "cosh", "tanh"):
            self.runtime[f"math_{name}"] = ir.Function(self.module, ft_dd, name=name)
        self.runtime["math_atan2"] = ir.Function(self.module, ft_dd2, name="atan2")
        self.runtime["math_pow"] = ir.Function(self.module, ft_dd2, name="pow")
        self.runtime["math_fmod"] = ir.Function(self.module, ft_dd2, name="fmod")
        self.runtime["math_log2"] = ir.Function(self.module, ft_dd, name="log2")
        # General call with kwargs: call_kw(callable, n_args, *tags, *data,
        #     n_kwargs, *names, *kw_tags, *kw_data, &out_tag, &out_data)
        ft = ir.FunctionType(void, [
            i8_ptr, i32, ir.PointerType(i32), ir.PointerType(i64),
            i32, ir.PointerType(i8_ptr), ir.PointerType(i32), ir.PointerType(i64),
            ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_call_kw"] = ir.Function(self.module, ft, name="fpy_cpython_call_kw")
        ft = ir.FunctionType(i8_ptr, [
            i8_ptr, i32, ir.PointerType(i32), ir.PointerType(i64),
            i32, ir.PointerType(i8_ptr), ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_call_kw_raw"] = ir.Function(self.module, ft, name="fpy_cpython_call_kw_raw")
        # dict merge: dict_a | dict_b -> new dict
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["dict_merge"] = ir.Function(self.module, ft, name="fastpy_dict_merge")

        # Dict methods
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["dict_pop"] = ir.Function(self.module, ft, name="fastpy_dict_pop")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])
        self.runtime["dict_pop_int"] = ir.Function(self.module, ft, name="fastpy_dict_pop_int")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr, i8_ptr])
        self.runtime["dict_setdefault_list"] = ir.Function(self.module, ft, name="fastpy_dict_setdefault_list")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr, i64])
        self.runtime["dict_setdefault_int"] = ir.Function(self.module, ft, name="fastpy_dict_setdefault_int")

        # divmod
        ft = ir.FunctionType(void, [i64, i64, ir.PointerType(i64), ir.PointerType(i64)])
        self.runtime["divmod"] = ir.Function(self.module, ft, name="fastpy_divmod")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["list_pop_int"] = ir.Function(self.module, ft, name="fastpy_list_pop_int")
        ft = ir.FunctionType(i64, [i8_ptr, i64])
        self.runtime["list_index"] = ir.Function(self.module, ft, name="fastpy_list_index")
        ft = ir.FunctionType(i64, [i8_ptr, i64])
        self.runtime["list_count"] = ir.Function(self.module, ft, name="fastpy_list_count")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr, i8_ptr])
        self.runtime["dict_get_default"] = ir.Function(self.module, ft, name="fastpy_dict_get_default")
        ft = ir.FunctionType(i32, [i8_ptr, i8_ptr])
        self.runtime["dict_has_key"] = ir.Function(self.module, ft, name="fastpy_dict_has_key")
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr])
        self.runtime["list_extend"] = ir.Function(self.module, ft, name="fastpy_list_extend")
        ft = ir.FunctionType(void, [i8_ptr])
        self.runtime["list_sort"] = ir.Function(self.module, ft, name="fastpy_list_sort")
        ft = ir.FunctionType(void, [i8_ptr])
        self.runtime["list_reverse_inplace"] = ir.Function(self.module, ft, name="fastpy_list_reverse")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])
        self.runtime["str_find"] = ir.Function(self.module, ft, name="fastpy_str_find")
        self.runtime["str_rfind"] = ir.Function(self.module, ft, name="fastpy_str_rfind")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])
        self.runtime["str_count"] = ir.Function(self.module, ft, name="fastpy_str_count")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["list_concat"] = ir.Function(self.module, ft, name="fastpy_list_concat")
        ft = ir.FunctionType(i32, [i8_ptr, i8_ptr])
        self.runtime["list_equal"] = ir.Function(self.module, ft, name="fastpy_list_equal")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])
        self.runtime["list_compare"] = ir.Function(self.module, ft, name="fastpy_list_compare")
        ft = ir.FunctionType(i8_ptr, [])
        self.runtime["tuple_new"] = ir.Function(self.module, ft, name="fastpy_tuple_new")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr, i8_ptr])
        self.runtime["zip3"] = ir.Function(self.module, ft, name="fastpy_zip3")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["list_sorted_by_key_int"] = ir.Function(self.module, ft, name="fastpy_list_sorted_by_key_int")
        self.runtime["list_sorted_by_key_str"] = ir.Function(self.module, ft, name="fastpy_list_sorted_by_key_str")
        self.runtime["list_map_int"] = ir.Function(self.module, ft, name="fastpy_list_map_int")
        self.runtime["list_filter_int"] = ir.Function(self.module, ft, name="fastpy_list_filter_int")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64])
        self.runtime["list_repeat"] = ir.Function(self.module, ft, name="fastpy_list_repeat")
        ft = ir.FunctionType(i8_ptr, [i64, i64, i64])
        self.runtime["range"] = ir.Function(self.module, ft, name="fastpy_range")
        ft = ir.FunctionType(i8_ptr, [double, i8_ptr])
        self.runtime["format_spec_float"] = ir.Function(self.module, ft, name="fastpy_format_spec_float")
        ft = ir.FunctionType(i8_ptr, [i64, i8_ptr])
        self.runtime["format_spec_int"] = ir.Function(self.module, ft, name="fastpy_format_spec_int")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["format_spec_str"] = ir.Function(self.module, ft, name="fastpy_format_spec_str")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64, i64, i64, i64])
        self.runtime["list_slice"] = ir.Function(self.module, ft, name="fastpy_list_slice")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64, i64, i64, i64, i64])
        self.runtime["list_slice_step"] = ir.Function(self.module, ft, name="fastpy_list_slice_step")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])  # str_join(sep, list) -> str
        self.runtime["str_join"] = ir.Function(self.module, ft, name="fastpy_str_join")

        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["tuple_to_str"] = ir.Function(self.module, ft, name="fastpy_tuple_to_str")

        # Dict operations
        ft = ir.FunctionType(i8_ptr, [])
        self.runtime["dict_new"] = ir.Function(self.module, ft, name="fastpy_dict_new")
        ft = ir.FunctionType(void, [i8_ptr, i64, i64])
        self.runtime["dict_set_int_int"] = ir.Function(self.module, ft, name="fastpy_dict_set_int_int")
        ft = ir.FunctionType(void, [i8_ptr, i64, i32, i64])
        self.runtime["dict_set_int_fv"] = ir.Function(self.module, ft, name="fastpy_dict_set_int_fv")
        ft = ir.FunctionType(void, [i8_ptr, i64, ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["dict_get_int_fv"] = ir.Function(self.module, ft, name="fastpy_dict_get_int_fv")
        ft = ir.FunctionType(i64, [i8_ptr, i64])
        self.runtime["dict_get_int_val"] = ir.Function(self.module, ft, name="fastpy_dict_get_int_val")
        ft = ir.FunctionType(i32, [i8_ptr, i64])
        self.runtime["dict_has_int_key"] = ir.Function(self.module, ft, name="fastpy_dict_has_int_key")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["dict_keys"] = ir.Function(self.module, ft, name="fastpy_dict_keys")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["dict_values"] = ir.Function(self.module, ft, name="fastpy_dict_values")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["dict_items"] = ir.Function(self.module, ft, name="fastpy_dict_items")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["dict_length"] = ir.Function(self.module, ft, name="fastpy_dict_length")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["dict_to_str"] = ir.Function(self.module, ft, name="fastpy_dict_to_str")

        # Closure support
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i32, i32])  # closure_new(func, n_params, n_captures)
        self.runtime["closure_new"] = ir.Function(self.module, ft, name="fastpy_closure_new")
        ft = ir.FunctionType(void, [i8_ptr, i32, i64])  # closure_set_capture(closure, idx, val)
        self.runtime["closure_set_capture"] = ir.Function(self.module, ft, name="fastpy_closure_set_capture")
        ft = ir.FunctionType(i64, [i8_ptr])  # closure_call0(closure)
        self.runtime["closure_call0"] = ir.Function(self.module, ft, name="fastpy_closure_call0")
        ft = ir.FunctionType(i64, [i8_ptr, i64])  # closure_call1(closure, a)
        self.runtime["closure_call1"] = ir.Function(self.module, ft, name="fastpy_closure_call1")
        ft = ir.FunctionType(i64, [i8_ptr, i64, i64])
        self.runtime["closure_call2"] = ir.Function(self.module, ft, name="fastpy_closure_call2")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])  # closure_call_list(closure, args_list)
        self.runtime["closure_call_list"] = ir.Function(self.module, ft, name="fastpy_closure_call_list")
        # Raw function pointer calls (for higher-order without closures)
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["call_ptr0"] = ir.Function(self.module, ft, name="fastpy_call_ptr0")
        ft = ir.FunctionType(i64, [i8_ptr, i64])
        self.runtime["call_ptr1"] = ir.Function(self.module, ft, name="fastpy_call_ptr1")
        ft = ir.FunctionType(i64, [i8_ptr, i64, i64])
        self.runtime["call_ptr2"] = ir.Function(self.module, ft, name="fastpy_call_ptr2")

        # CPython bridge: import, getattr, call for .pyd modules
        ft = ir.FunctionType(i8_ptr, [i8_ptr])  # fpy_cpython_import(name) -> PyObject*
        self.runtime["cpython_import"] = ir.Function(self.module, ft, name="fpy_cpython_import")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])  # fpy_cpython_getattr(obj, name) -> PyObject*
        self.runtime["cpython_getattr"] = ir.Function(self.module, ft, name="fpy_cpython_getattr")
        # call1(callable, tag, data, &out_tag, &out_data)
        ft = ir.FunctionType(void, [i8_ptr, i32, i64, ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_call1"] = ir.Function(self.module, ft, name="fpy_cpython_call1")
        # call2(callable, t1, d1, t2, d2, &out_tag, &out_data)
        ft = ir.FunctionType(void, [i8_ptr, i32, i64, i32, i64,
                                     ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_call2"] = ir.Function(self.module, ft, name="fpy_cpython_call2")
        # call0(callable, &out_tag, &out_data)
        ft = ir.FunctionType(void, [i8_ptr, ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_call0"] = ir.Function(self.module, ft, name="fpy_cpython_call0")
        # call3(callable, t1,d1, t2,d2, t3,d3, &out_tag, &out_data)
        ft = ir.FunctionType(void, [i8_ptr, i32, i64, i32, i64, i32, i64,
                                     ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_call3"] = ir.Function(self.module, ft, name="fpy_cpython_call3")
        # to_fv(pyobj, &out_tag, &out_data) — convert PyObject* to FpyValue
        ft = ir.FunctionType(void, [i8_ptr, ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["cpython_to_fv"] = ir.Function(self.module, ft, name="fpy_cpython_to_fv")
        # Direct len/bool on PyObject*
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["cpython_len"] = ir.Function(self.module, ft, name="fpy_cpython_len")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["cpython_bool"] = ir.Function(self.module, ft, name="fpy_cpython_bool")
        # exec_get(code, name) -> PyObject*: exec Python code, return named object
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["cpython_exec_get"] = ir.Function(self.module, ft, name="fpy_cpython_exec_get")

        # enumerate and zip
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i64])
        self.runtime["enumerate"] = ir.Function(self.module, ft, name="fastpy_enumerate")
        ft = ir.FunctionType(i8_ptr, [i8_ptr, i8_ptr])
        self.runtime["zip"] = ir.Function(self.module, ft, name="fastpy_zip")

        # Mutable closure cells
        ft = ir.FunctionType(i8_ptr, [i64])
        self.runtime["cell_new"] = ir.Function(self.module, ft, name="fastpy_cell_new")
        ft = ir.FunctionType(void, [i8_ptr, i64])
        self.runtime["cell_set"] = ir.Function(self.module, ft, name="fastpy_cell_set")
        ft = ir.FunctionType(i64, [i8_ptr])
        self.runtime["cell_get"] = ir.Function(self.module, ft, name="fastpy_cell_get")

        # Object system
        ft = ir.FunctionType(i32, [i8_ptr, i32])  # register_class(name, parent_id) -> class_id
        self.runtime["register_class"] = ir.Function(self.module, ft, name="fastpy_register_class")
        ft = ir.FunctionType(void, [i32, i8_ptr, i8_ptr, i32, i32])  # register_method(class_id, name, func, argc, returns)
        self.runtime["register_method"] = ir.Function(self.module, ft, name="fastpy_register_method")
        ft = ir.FunctionType(i8_ptr, [i32])  # obj_new(class_id) -> obj*
        self.runtime["obj_new"] = ir.Function(self.module, ft, name="fastpy_obj_new")
        # Tagged-value attribute access (post-refactor). The old typed
        # variants (obj_set_int/float/str, obj_get_int/float/str) were
        # replaced — they're no longer emitted by the compiler.
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr, i32, i64])
        self.runtime["obj_set_fv"] = ir.Function(self.module, ft, name="fastpy_obj_set_fv")
        # obj_get_fv writes tag+data via out pointers (MSVC-ABI-safe)
        ft = ir.FunctionType(void, [i8_ptr, i8_ptr,
                                     ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["obj_get_fv"] = ir.Function(self.module, ft, name="fastpy_obj_get_fv")
        # Static-slot fast paths — bypass name lookup
        ft = ir.FunctionType(void, [i8_ptr, i32, i32, i64])
        self.runtime["obj_set_slot"] = ir.Function(self.module, ft, name="fastpy_obj_set_slot")
        ft = ir.FunctionType(void, [i8_ptr, i32,
                                     ir.PointerType(i32), ir.PointerType(i64)])
        self.runtime["obj_get_slot"] = ir.Function(self.module, ft, name="fastpy_obj_get_slot")
        # Class slot count registration
        ft = ir.FunctionType(void, [i32, i32])
        self.runtime["set_class_slot_count"] = ir.Function(
            self.module, ft, name="fastpy_set_class_slot_count")
        # Per-slot name registration (lets obj_get_fv/obj_set_fv find the
        # slot when the compiler couldn't determine it statically)
        ft = ir.FunctionType(void, [i32, i32, i8_ptr])
        self.runtime["register_slot_name"] = ir.Function(
            self.module, ft, name="fastpy_register_slot_name")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr])  # obj_call_method0(obj, name) -> result
        self.runtime["obj_call_method0"] = ir.Function(self.module, ft, name="fastpy_obj_call_method0")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr, i64])
        self.runtime["obj_call_method1"] = ir.Function(self.module, ft, name="fastpy_obj_call_method1")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr, i64, i64])
        self.runtime["obj_call_method2"] = ir.Function(self.module, ft, name="fastpy_obj_call_method2")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr, i64, i64, i64])
        self.runtime["obj_call_method3"] = ir.Function(self.module, ft, name="fastpy_obj_call_method3")
        ft = ir.FunctionType(i64, [i8_ptr, i8_ptr, i64, i64, i64, i64])
        self.runtime["obj_call_method4"] = ir.Function(self.module, ft, name="fastpy_obj_call_method4")
        ft = ir.FunctionType(void, [i8_ptr])  # obj_call_init0(obj)
        self.runtime["obj_call_init0"] = ir.Function(self.module, ft, name="fastpy_obj_call_init0")
        ft = ir.FunctionType(void, [i8_ptr, i64])
        self.runtime["obj_call_init1"] = ir.Function(self.module, ft, name="fastpy_obj_call_init1")
        ft = ir.FunctionType(void, [i8_ptr, i64, i64])
        self.runtime["obj_call_init2"] = ir.Function(self.module, ft, name="fastpy_obj_call_init2")
        ft = ir.FunctionType(void, [i8_ptr, i64, i64, i64])
        self.runtime["obj_call_init3"] = ir.Function(self.module, ft, name="fastpy_obj_call_init3")
        ft = ir.FunctionType(void, [i8_ptr, i64, i64, i64, i64])
        self.runtime["obj_call_init4"] = ir.Function(self.module, ft, name="fastpy_obj_call_init4")
        ft = ir.FunctionType(i32, [i8_ptr, i32])  # isinstance(obj, class_id) -> bool
        self.runtime["isinstance"] = ir.Function(self.module, ft, name="fastpy_isinstance")
        ft = ir.FunctionType(i8_ptr, [i8_ptr])
        self.runtime["obj_to_str"] = ir.Function(self.module, ft, name="fastpy_obj_to_str")
        ft = ir.FunctionType(double, [i8_ptr, i8_ptr])
        self.runtime["obj_call_method0_double"] = ir.Function(self.module, ft, name="fastpy_obj_call_method0_double")
        ft = ir.FunctionType(double, [i8_ptr, i8_ptr, i64])
        self.runtime["obj_call_method1_double"] = ir.Function(self.module, ft, name="fastpy_obj_call_method1_double")

        # Safe division (checks for zero, raises ZeroDivisionError)
        ft = ir.FunctionType(i64, [i64, i64])
        self.runtime["safe_div"] = ir.Function(self.module, ft, name="fastpy_safe_div")
        ft = ir.FunctionType(double, [double, double])
        self.runtime["safe_fdiv"] = ir.Function(self.module, ft, name="fastpy_safe_fdiv")
        ft = ir.FunctionType(double, [i64, i64])
        self.runtime["safe_int_fdiv"] = ir.Function(self.module, ft, name="fastpy_safe_int_fdiv")

        # Exception system (flag-based)
        # int fastpy_exc_pending(void)
        ft = ir.FunctionType(i32, [])
        self.runtime["exc_pending"] = ir.Function(self.module, ft, name="fastpy_exc_pending")
        # void fastpy_exc_unhandled(void) — print and exit
        ft = ir.FunctionType(void, [])
        self.runtime["exc_unhandled"] = ir.Function(self.module, ft, name="fastpy_exc_unhandled")
        # void fastpy_raise(int type, const char *msg)
        ft = ir.FunctionType(void, [i32, i8_ptr])
        self.runtime["raise"] = ir.Function(self.module, ft, name="fastpy_raise")
        # int fastpy_exc_get_type(void)
        ft = ir.FunctionType(i32, [])
        self.runtime["exc_get_type"] = ir.Function(self.module, ft, name="fastpy_exc_get_type")
        # const char* fastpy_exc_get_msg(void)
        ft = ir.FunctionType(i8_ptr, [])
        self.runtime["exc_get_msg"] = ir.Function(self.module, ft, name="fastpy_exc_get_msg")
        # void fastpy_exc_clear(void)
        ft = ir.FunctionType(void, [])
        self.runtime["exc_clear"] = ir.Function(self.module, ft, name="fastpy_exc_clear")
        # int fastpy_exc_name_to_id(const char *name)
        ft = ir.FunctionType(i32, [i8_ptr])
        self.runtime["exc_name_to_id"] = ir.Function(self.module, ft, name="fastpy_exc_name_to_id")
        # ExceptionGroup inner type tracking
        ft = ir.FunctionType(void, [i32])
        self.runtime["exc_set_group_inner"] = ir.Function(self.module, ft, name="fastpy_exc_set_group_inner")
        ft = ir.FunctionType(i32, [])
        self.runtime["exc_get_group_inner"] = ir.Function(self.module, ft, name="fastpy_exc_get_group_inner")
        # Reference counting: tag-dispatching incref/decref
        ft = ir.FunctionType(void, [i32, i64])
        self.runtime["rc_incref"] = ir.Function(self.module, ft, name="fpy_rc_incref")
        self.runtime["rc_decref"] = ir.Function(self.module, ft, name="fpy_rc_decref")

        # Closure return tag: set before ret, read after call
        ft = ir.FunctionType(void, [i32])
        self.runtime["set_ret_tag"] = ir.Function(self.module, ft, name="fastpy_set_ret_tag")
        ft = ir.FunctionType(i32, [])
        self.runtime["get_ret_tag"] = ir.Function(self.module, ft, name="fastpy_get_ret_tag")

        # Write functions — only write_str and write_space remain
        # (used for print(sep=, end=) handling). Typed write_int/float/bool/none
        # were superseded by fv_write.
        ft = ir.FunctionType(void, [i8_ptr])
        self.runtime["write_str"] = ir.Function(self.module, ft, name="fastpy_write_str")
        ft = ir.FunctionType(void, [])
        self.runtime["write_space"] = ir.Function(self.module, ft, name="fastpy_write_space")

    def _make_string_constant(self, value: str) -> ir.Constant:
        """Create a global string constant and return a pointer to it.

        Deduplicates — returns the same GEP for identical string values.
        """
        if not hasattr(self, '_str_constants'):
            self._str_constants: dict[str, ir.GlobalVariable] = {}
        global_str = self._str_constants.get(value)
        if global_str is None:
            encoded = value.encode("utf-8") + b"\x00"
            str_type = ir.ArrayType(i8, len(encoded))
            name = f".str.{self._str_counter}"
            self._str_counter += 1
            global_str = ir.GlobalVariable(self.module, str_type, name=name)
            global_str.global_constant = True
            global_str.linkage = "private"
            global_str.initializer = ir.Constant(str_type, bytearray(encoded))
            # unnamed_addr allows LLVM/linker to merge equivalent constants
            global_str.unnamed_addr = True
            self._str_constants[value] = global_str

        # Get pointer to first element
        zero = ir.Constant(i64, 0)
        return self.builder.gep(global_str, [zero, zero], inbounds=True)

    # -------------------------------------------------------------
    # FpyValue helpers (Phase 1 of tagged-value refactor)
    #
    # In the migrated world, every Python value is an FpyValue (a
    # {tag, data} struct). These helpers bridge between bare LLVM
    # types (i64/double/i8*) and FpyValue. During migration both
    # paths coexist; eventually the bare-type paths go away.
    # -------------------------------------------------------------

    def _fv_build(self, tag: int, data_i64: ir.Value) -> ir.Value:
        """Build an FpyValue with the given tag and i64 data payload."""
        fv = ir.Constant(fpy_val, ir.Undefined)
        fv = self.builder.insert_value(fv, ir.Constant(i32, tag), 0)
        fv = self.builder.insert_value(fv, data_i64, 1)
        return fv

    def _fv_from_int(self, value: ir.Value) -> ir.Value:
        """Wrap an i64 in FpyValue(INT)."""
        if isinstance(value.type, ir.IntType) and value.type.width != 64:
            value = self.builder.zext(value, i64) if value.type.width < 64 \
                else self.builder.trunc(value, i64)
        return self._fv_build(FPY_TAG_INT, value)

    def _fv_from_bool(self, value: ir.Value) -> ir.Value:
        """Wrap an i1 or i32 in FpyValue(BOOL)."""
        if isinstance(value.type, ir.IntType):
            if value.type.width < 64:
                value = self.builder.zext(value, i64)
            elif value.type.width > 64:
                value = self.builder.trunc(value, i64)
        return self._fv_build(FPY_TAG_BOOL, value)

    def _fv_from_float(self, value: ir.Value) -> ir.Value:
        """Wrap a double in FpyValue(FLOAT) by bitcasting to i64."""
        data = self.builder.bitcast(value, i64)
        return self._fv_build(FPY_TAG_FLOAT, data)

    def _fv_from_str(self, value: ir.Value) -> ir.Value:
        """Wrap an i8* in FpyValue(STR) by ptrtoint."""
        data = self.builder.ptrtoint(value, i64)
        return self._fv_build(FPY_TAG_STR, data)

    def _fv_from_list(self, value: ir.Value) -> ir.Value:
        """Wrap an i8* (FpyList*) in FpyValue(LIST) by ptrtoint."""
        data = self.builder.ptrtoint(value, i64)
        return self._fv_build(FPY_TAG_LIST, data)

    def _fv_from_obj(self, value: ir.Value) -> ir.Value:
        """Wrap an i8* (FpyObj*) in FpyValue(OBJ) by ptrtoint."""
        data = self.builder.ptrtoint(value, i64)
        return self._fv_build(FPY_TAG_OBJ, data)

    def _fv_from_dict(self, value: ir.Value) -> ir.Value:
        """Wrap an i8* (FpyDict*) in FpyValue(DICT) by ptrtoint."""
        data = self.builder.ptrtoint(value, i64)
        return self._fv_build(FPY_TAG_DICT, data)

    def _fv_none(self) -> ir.Value:
        """Build FpyValue(NONE)."""
        return self._fv_build(FPY_TAG_NONE, ir.Constant(i64, 0))

    def _fv_tag(self, fv: ir.Value) -> ir.Value:
        """Extract the i32 tag from an FpyValue."""
        return self.builder.extract_value(fv, 0)

    def _fv_data_i64(self, fv: ir.Value) -> ir.Value:
        """Extract the i64 data payload from an FpyValue."""
        return self.builder.extract_value(fv, 1)

    def _fv_as_int(self, fv: ir.Value) -> ir.Value:
        """Extract data as i64 (assumes tag is INT or BOOL)."""
        return self._fv_data_i64(fv)

    def _fv_as_float(self, fv: ir.Value) -> ir.Value:
        """Extract data as double (assumes tag is FLOAT)."""
        return self.builder.bitcast(self._fv_data_i64(fv), double)

    def _fv_as_str(self, fv: ir.Value) -> ir.Value:
        """Extract data as i8* (assumes tag is STR)."""
        return self.builder.inttoptr(self._fv_data_i64(fv), i8_ptr)

    def _fv_as_ptr(self, fv: ir.Value) -> ir.Value:
        """Extract data as i8* (for list/obj pointers)."""
        return self.builder.inttoptr(self._fv_data_i64(fv), i8_ptr)

    def _fv_unpack(self, fv: ir.Value) -> tuple[ir.Value, ir.Value]:
        """Unpack an FpyValue into (tag, data_i64) — the ABI-stable pair we pass to runtime."""
        return self._fv_tag(fv), self._fv_data_i64(fv)

    def _fv_call_print(self, fv: ir.Value) -> None:
        """Emit fastpy_fv_print(fv)."""
        tag, data = self._fv_unpack(fv)
        self.builder.call(self.runtime["fv_print"], [tag, data])

    def _fv_call_write(self, fv: ir.Value) -> None:
        """Emit fastpy_fv_write(fv)."""
        tag, data = self._fv_unpack(fv)
        self.builder.call(self.runtime["fv_write"], [tag, data])

    def _fv_call_repr(self, fv: ir.Value) -> ir.Value:
        """Emit fastpy_fv_repr(fv) → i8* string."""
        tag, data = self._fv_unpack(fv)
        return self.builder.call(self.runtime["fv_repr"], [tag, data])

    def _fv_call_str(self, fv: ir.Value) -> ir.Value:
        """Emit fastpy_fv_str(fv) → i8* string (strings pass through without quotes)."""
        tag, data = self._fv_unpack(fv)
        return self.builder.call(self.runtime["fv_str"], [tag, data])

    def _fv_call_truthy(self, fv: ir.Value) -> ir.Value:
        """Emit fastpy_fv_truthy(fv) → i1."""
        tag, data = self._fv_unpack(fv)
        i32_result = self.builder.call(self.runtime["fv_truthy"], [tag, data])
        return self.builder.icmp_signed("!=", i32_result, ir.Constant(i32, 0))

    def _fv_wrap(self, value: ir.Value) -> ir.Value:
        """Wrap any bare LLVM value into an FpyValue, inferring tag from LLVM type.

        Pointer types are tagged STR by default — callers that know it's a
        list/obj should use _fv_from_list/_fv_from_obj instead.
        """
        if isinstance(value.type, ir.IntType):
            if value.type.width == 32:
                return self._fv_from_bool(value)
            return self._fv_from_int(value)
        if isinstance(value.type, ir.DoubleType):
            return self._fv_from_float(value)
        if isinstance(value.type, ir.PointerType):
            return self._fv_from_str(value)
        raise CodeGenError(f"Cannot wrap LLVM type {value.type} in FpyValue")

    def generate(self, tree: ast.Module) -> str:
        """Generate LLVM IR from a Python AST. Returns IR as string."""
        # Pass 0: scan for lambda assignments and create hidden functions
        self._lambda_counter = 0
        self._lambda_map: dict[int, str] = {}  # id(Lambda node) -> func name
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Lambda):
                    self._declare_lambda(node.targets[0].id, node.value)

        # Pass 0.5: scan for nested functions (closures) inside other functions
        self._closure_info: dict[str, list[str]] = {}  # inner_name -> [captured_vars]
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self._scan_for_closures(node)

        # Pass 0.7: scan for global variable declarations and create LLVM globals.
        # Infer the type from module-level assignments to the global name.
        global_types: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name):
                    name = node.targets[0].id
                    if isinstance(node.value, (ast.List, ast.ListComp)):
                        global_types[name] = "list"
                    elif isinstance(node.value, (ast.Dict, ast.DictComp)):
                        global_types[name] = "dict"
                    elif isinstance(node.value, ast.Constant):
                        if isinstance(node.value.value, str):
                            global_types[name] = "str"
                        elif isinstance(node.value.value, float):
                            global_types[name] = "float"

        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                for name in node.names:
                    if name not in self._global_vars:
                        gtype = global_types.get(name)
                        if gtype in ("list", "dict", "str"):
                            gvar = ir.GlobalVariable(self.module, i8_ptr,
                                                     name=f"fastpy.global.{name}")
                            gvar.initializer = ir.Constant(i8_ptr, None)
                            gvar.linkage = "private"
                            tag = gtype if gtype != "list" else "list:int"
                            self._global_vars[name] = (gvar, tag)
                        elif gtype == "float":
                            gvar = ir.GlobalVariable(self.module, double,
                                                     name=f"fastpy.global.{name}")
                            gvar.initializer = ir.Constant(double, 0.0)
                            gvar.linkage = "private"
                            self._global_vars[name] = (gvar, "float")
                        else:
                            gvar = ir.GlobalVariable(self.module, i64,
                                                     name=f"fastpy.global.{name}")
                            gvar.initializer = ir.Constant(i64, 0)
                            gvar.linkage = "private"
                            self._global_vars[name] = (gvar, "int")

        # Pass 0.75: analyze call sites to determine parameter types
        self._call_site_param_types: dict[str, list[str | None]] = {}
        # Distinct call signatures per function (for monomorphization).
        # Maps func_name -> list of unique signature tuples (arg_types).
        self._function_signatures: dict[str, list[tuple]] = {}
        # Maps (func_name, signature) -> specialized mangled name when
        # the function is monomorphized. Populated in _declare_user_function.
        self._monomorphized: dict[str, list[tuple]] = {}
        # Maps class_name -> list of constructor signatures when the class
        # is monomorphized (same class name used with scalar-conflicting
        # constructor arg types). Populated in _declare_class.
        self._monomorphized_classes: dict[str, list[tuple]] = {}
        self._analyze_call_sites(tree)

        # Pass 0.8: discover static attribute slots per class
        self._assign_attribute_slots(tree)

        # Pass 1: forward-declare all user functions and class methods
        # Also scan for nested classes (class B inside class A)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self._declare_user_function(node)
            elif isinstance(node, ast.ClassDef):
                self._declare_class(node)
                # Declare nested classes
                for item in node.body:
                    if isinstance(item, ast.ClassDef):
                        self._declare_class(item)

        # Pass 1.1: hoist simple inner functions (no captures) to module
        # level so call sites inside their outer function can find them.
        # This runs after the initial declaration pass so _function_signatures
        # etc. are set up.
        for inner in getattr(self, "_hoist_inner_funcs", []):
            if inner.name not in self._user_functions:
                self._declare_user_function(inner)

        # Pass 1.5: generate code for lambda functions
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Lambda):
                    var_name = node.targets[0].id
                    if var_name in self._user_functions:
                        lam = node.value
                        info = self._user_functions[var_name]
                        self._emit_lambda_body(info.func, lam)

        # Pass 2: generate code for user functions and class methods
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self._emit_function_def(node)
            elif isinstance(node, ast.ClassDef):
                self._emit_class_methods(node)

        # Pass 2.1: emit bodies of hoisted inner functions
        for inner in getattr(self, "_hoist_inner_funcs", []):
            if inner.name in self._user_functions:
                # Only emit if not already emitted
                info = self._user_functions[inner.name]
                if not info.func.blocks:
                    self._emit_function_def(inner)

        # Pass 3: generate fastpy_main from module-level statements
        func_type = ir.FunctionType(void, [])
        main_fn = ir.Function(self.module, func_type, name="fastpy_main")
        entry = main_fn.append_basic_block(name="entry")
        self.function = main_fn
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        # Pre-populate module-level variables with globals so that
        # assignments like `data = []` at module level store to the
        # global variable (which functions access via `global data`).
        for gname, (gvar, gtag) in self._global_vars.items():
            self.variables[gname] = (gvar, gtag)
        self._loop_stack = []

        # Register classes with the runtime
        for cls_info in self._user_classes.values():
            self._emit_class_registration(cls_info)

        # Pre-scan module-level list append patterns
        module_stmts = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        self._prescan_list_append_types(module_stmts)
        self._current_scope_stmts = module_stmts

        # Apply decorators to top-level functions: @deco def f(...) → f = deco(f)
        # For @deco(args), this is f = deco(args)(f) — two-step application.
        for node in tree.body:
            if (isinstance(node, ast.FunctionDef)
                    and node.decorator_list
                    and node.name in self._user_functions):
                for deco in node.decorator_list:
                    # Skip built-in decorators (handled at class level)
                    if isinstance(deco, ast.Name) and deco.id in (
                            "staticmethod", "classmethod", "property"):
                        continue
                    if isinstance(deco, ast.Attribute):
                        continue  # @x.setter etc — handled by class

                    info = self._user_functions[node.name]
                    func_ptr = self.builder.ptrtoint(info.func, i64)

                    # @deco — simple decorator: f = deco(f)
                    if isinstance(deco, ast.Name) and deco.id in self._user_functions:
                        deco_info = self._user_functions[deco.id]
                        if deco_info.uses_fv_abi:
                            fv = self._fv_from_int(func_ptr)
                            result = self.builder.call(deco_info.func, [fv])
                            self._store_variable(node.name, result, "closure")
                        else:
                            result = self.builder.call(deco_info.func, [func_ptr])
                            self._store_variable(node.name,
                                self.builder.inttoptr(result, i8_ptr), "closure")

                    # @deco(args) — decorator with args: f = deco(args)(f)
                    elif isinstance(deco, ast.Call):
                        # Step 1: call deco(args) → get the actual decorator
                        actual_deco = self._emit_expr_value(deco)
                        if isinstance(actual_deco.type, ir.IntType):
                            actual_deco = self.builder.inttoptr(actual_deco, i8_ptr)
                        # Step 2: call actual_deco(f) → get the wrapped function
                        # If f uses FpyValue ABI, create a thin i64-ABI wrapper
                        # so call_ptr0/1/2 can call it correctly.
                        if info.uses_fv_abi:
                            wrapper = self._get_or_emit_i64_wrapper(info)
                            wrapper_ptr = self.builder.ptrtoint(wrapper, i64)
                        else:
                            wrapper_ptr = func_ptr
                        result = self.builder.call(
                            self.runtime["closure_call1"],
                            [actual_deco, wrapper_ptr])
                        self._store_variable(node.name,
                            self.builder.inttoptr(result, i8_ptr), "closure")

        # Compile CPython generators: functions marked as needing CPython's
        # coroutine support get compiled via exec_get and stored as pyobj.
        for node in tree.body:
            if (isinstance(node, ast.FunctionDef)
                    and node.name in getattr(self, '_cpython_generators', set())):
                self._emit_cpython_generator(node, node.name)

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                self._emit_stmt(node)

        if not self.builder.block.is_terminated:
            self.builder.ret_void()

        return str(self.module)

    def _scan_for_closures(self, outer_func: ast.FunctionDef,
                            _name_prefix: str | None = None,
                            _all_outer_locals: set | None = None) -> None:
        """Find nested function defs and identify captured variables.
        Recurses into nested functions to support arbitrary nesting depth.
        """
        outer_params = {arg.arg for arg in outer_func.args.args}
        if outer_func.args.vararg:
            outer_params.add(outer_func.args.vararg.arg)
        # Collect variables assigned in the outer function body
        outer_locals = set(outer_params)
        for stmt in outer_func.body:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if isinstance(tgt, ast.Name):
                            outer_locals.add(tgt.id)
                # Inner function names are also locals
                if isinstance(n, ast.FunctionDef):
                    outer_locals.add(n.name)

        # Merge with all enclosing scope locals (for multi-level capture)
        all_locals = set(outer_locals)
        if _all_outer_locals:
            all_locals |= _all_outer_locals

        prefix = _name_prefix if _name_prefix else outer_func.name

        for node in outer_func.body:
            if isinstance(node, ast.FunctionDef):
                inner_name = node.name
                inner_params = {arg.arg for arg in node.args.args}
                if node.args.vararg:
                    inner_params.add(node.args.vararg.arg)

                # Detect nonlocal declarations
                nonlocal_vars = set()
                for n in ast.walk(node):
                    if isinstance(n, ast.Nonlocal):
                        nonlocal_vars.update(n.names)

                # Collect all names defined locally inside this function
                # (assignments, for targets, nested defs) BUT exclude
                # names declared as nonlocal (those are captures, not locals)
                inner_locals = set(inner_params)
                for n in ast.walk(node):
                    if isinstance(n, ast.Assign):
                        for tgt in n.targets:
                            if isinstance(tgt, ast.Name):
                                if tgt.id not in nonlocal_vars:
                                    inner_locals.add(tgt.id)
                    if isinstance(n, ast.For) and isinstance(n.target, ast.Name):
                        if n.target.id not in nonlocal_vars:
                            inner_locals.add(n.target.id)
                    if isinstance(n, ast.FunctionDef) and n is not node:
                        inner_locals.add(n.name)

                # Find free variables: names used in inner but defined in
                # any enclosing scope, NOT defined locally
                free_vars = []
                for n in ast.walk(node):
                    if isinstance(n, ast.Name) and n.id not in inner_locals:
                        if n.id in all_locals and n.id not in free_vars:
                            free_vars.append(n.id)

                if not free_vars:
                    if not hasattr(self, "_hoist_inner_funcs"):
                        self._hoist_inner_funcs = []
                    self._hoist_inner_funcs.append(node)
                    # Still recurse into no-capture functions for their
                    # own inner defs
                    self._scan_for_closures(
                        node, f"{prefix}.{inner_name}", all_locals)
                    continue

                if free_vars:
                    full_name = f"{prefix}.{inner_name}"
                    self._closure_info[full_name] = free_vars
                    # Track which captures are mutable (nonlocal)
                    if not hasattr(self, '_closure_nonlocals'):
                        self._closure_nonlocals = {}
                    self._closure_nonlocals[full_name] = nonlocal_vars

                    # Declare inner function: explicit params + capture params
                    # Mutable captures are i8* (cell pointers), immutable are i64
                    # If the inner function uses *args, include it as a single
                    # i8* parameter (pointer to the args list).
                    explicit_params = [arg.arg for arg in node.args.args]
                    if node.args.vararg:
                        explicit_params.append(node.args.vararg.arg)
                    all_params = explicit_params + free_vars
                    param_types = [i64] * len(node.args.args)
                    if node.args.vararg:
                        param_types.append(i8_ptr)  # args list pointer
                    for v in free_vars:
                        param_types.append(i8_ptr if v in nonlocal_vars else i64)

                    has_return = any(
                        isinstance(n, ast.Return) and n.value is not None
                        for n in ast.walk(node)
                    )
                    ret_type = i64 if has_return else void

                    func_type = ir.FunctionType(ret_type, param_types)
                    fn_name = f"fastpy.closure.{full_name}"
                    func = ir.Function(self.module, func_type, name=fn_name)
                    for param, pname in zip(func.args, all_params):
                        param.name = pname

                    # Detect if the closure returns a boolean.
                    # Traces through variable assignments so that
                    # `result = x > n; return result` is also detected.
                    ret_tag = "void"
                    if ret_type == i64:
                        ret_tag = "int"
                        _cvar_exprs: dict[str, ast.expr] = {}
                        for _s in node.body:
                            if (isinstance(_s, ast.Assign)
                                    and len(_s.targets) == 1
                                    and isinstance(_s.targets[0], ast.Name)):
                                _cvar_exprs[_s.targets[0].id] = _s.value
                        for rn in node.body:
                            if isinstance(rn, ast.Return) and rn.value is not None:
                                v = rn.value
                                if isinstance(v, ast.Name) and v.id in _cvar_exprs:
                                    v = _cvar_exprs[v.id]
                                if isinstance(v, ast.Compare):
                                    ret_tag = "bool"
                                elif (isinstance(v, ast.UnaryOp)
                                        and isinstance(v.op, ast.Not)):
                                    ret_tag = "bool"
                                elif (isinstance(v, ast.Call)
                                        and isinstance(v.func, ast.Name)
                                        and v.func.id in ("bool", "isinstance")):
                                    ret_tag = "bool"
                    # Register as a special closure function
                    self._user_functions[full_name] = FuncInfo(
                        func=func, ret_tag=ret_tag,
                        param_count=len(node.args.args),  # explicit params only
                        defaults=node.args.defaults,
                        min_args=len(node.args.args) - len(node.args.defaults),
                    )

                    # Recurse BEFORE emitting body: scan this inner function
                    # for its own inner functions so they're registered in
                    # _closure_info before the body tries to use them.
                    self._scan_for_closures(
                        node, full_name, all_locals)

                    # Generate body (may reference nested closures)
                    self._emit_closure_body(func, node, free_vars)

    def _get_or_emit_i64_wrapper(self, info: "FuncInfo") -> ir.Function:
        """Create a thin i64-ABI wrapper for a FpyValue-ABI function.
        Needed when the function is passed as a raw function pointer
        (e.g., to decorators) and called via call_ptr0/1/2.
        The wrapper receives i64 args, wraps them as FpyValues, calls
        the real function, and returns the result data as i64."""
        wrapper_name = f"{info.func.name}.__i64_wrap"
        # Check if already created
        try:
            return self.module.get_global(wrapper_name)
        except KeyError:
            pass
        # Create wrapper: i64 params → FpyValue call → i64 return
        n_params = info.param_count
        param_types = [i64] * n_params
        wrapper_type = ir.FunctionType(i64, param_types)
        wrapper = ir.Function(self.module, wrapper_type, name=wrapper_name)
        block = wrapper.append_basic_block("entry")
        b = ir.IRBuilder(block)
        # Wrap each i64 arg as FpyValue(INT)
        fv_args = []
        for param in wrapper.args:
            tag = ir.Constant(i32, FPY_TAG_INT)
            fv = b.insert_value(ir.Constant(fpy_val, ir.Undefined), tag, 0)
            fv = b.insert_value(fv, param, 1)
            fv_args.append(fv)
        # Call the real function
        if info.func.return_value.type == void:
            b.call(info.func, fv_args)
            b.ret(ir.Constant(i64, 0))
        else:
            result = b.call(info.func, fv_args)
            # Extract data from FpyValue result
            data = b.extract_value(result, 1)
            b.ret(data)
        return wrapper

    def _emit_nested_funcdef(self, node: ast.FunctionDef) -> None:
        """Handle a nested function definition — either a closure or a simple inner def."""
        # Find the outer function name by checking the current function's LLVM name
        # Look up if this is a closure
        for full_name, captures in self._closure_info.items():
            if full_name.endswith(f".{node.name}"):
                # This is a closure — create closure object
                closure_func = self._user_functions[full_name].func
                func_ptr = self.builder.bitcast(closure_func, i8_ptr)
                n_params = len(node.args.args)
                n_captures = len(captures)

                nonlocals = self._closure_nonlocals.get(full_name, set())

                closure = self.builder.call(self.runtime["closure_new"], [
                    func_ptr,
                    ir.Constant(i32, n_params),
                    ir.Constant(i32, n_captures),
                ])

                # Set captured values. For mutable captures (nonlocal),
                # save the cell pointer so we can read back after the call.
                cell_allocas: dict[str, ir.AllocaInstr] = {}
                for i, var_name in enumerate(captures):
                    if var_name in nonlocals:
                        # Mutable capture: create a cell and pass cell pointer
                        current_val = self._load_variable(var_name, node)
                        cell = self.builder.call(self.runtime["cell_new"], [current_val])
                        cell_as_i64 = self.builder.ptrtoint(cell, i64)
                        self.builder.call(self.runtime["closure_set_capture"], [
                            closure, ir.Constant(i32, i), cell_as_i64])
                        # Save cell pointer for read-back after closure call
                        cell_alloca = self._create_entry_alloca(i8_ptr,
                                                                f"cell.{var_name}")
                        self.builder.store(cell, cell_alloca)
                        cell_allocas[var_name] = cell_alloca
                        # Also mark the outer variable as cell-backed so
                        # inline calls to g() will read from the cell
                        self.variables[var_name] = (cell_alloca, "cell")
                    else:
                        val = self._load_variable(var_name, node)
                        if isinstance(val.type, ir.PointerType):
                            val = self.builder.ptrtoint(val, i64)
                        elif isinstance(val.type, ir.IntType) and val.type.width != 64:
                            val = self.builder.zext(val, i64)
                        self.builder.call(self.runtime["closure_set_capture"], [
                            closure, ir.Constant(i32, i), val])

                # Store closure as a variable with the inner function's name
                self._store_variable(node.name, closure, "closure")
                return

        # Not a closure — just a regular nested def (no captures)
        # Not a closure — just a regular nested def (no captures).
        # Already compiled at top level via hoisting. Store an i64-ABI
        # wrapper as the variable so it's safe to call through call_ptr
        # (hoisted functions use FpyValue ABI which is incompatible with
        # the i64 calling convention used by call_ptr0/1/2).
        if node.name in self._user_functions:
            info = self._user_functions[node.name]
            if info.uses_fv_abi:
                wrapper = self._get_or_emit_i64_wrapper(info)
                wrapper_ptr = self.builder.bitcast(wrapper, i8_ptr)
                # Wrap in a zero-capture closure so closure_call works too
                closure = self.builder.call(self.runtime["closure_new"], [
                    wrapper_ptr,
                    ir.Constant(i32, info.param_count),
                    ir.Constant(i32, 0),
                ])
                self._store_variable(node.name, closure, "closure")
            else:
                func_ptr = self.builder.ptrtoint(info.func, i64)
                self._store_variable(node.name, func_ptr, "int")

    def _emit_closure_body(self, func: ir.Function, node: ast.FunctionDef,
                           captures: list[str]) -> None:
        """Generate code for a closure's body."""
        saved = (self.function, self.builder, self.variables, self._loop_stack)

        self.function = func
        entry = func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self._loop_stack = []

        # Detect which captures are mutable
        nonlocal_vars = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Nonlocal):
                nonlocal_vars.update(n.names)

        explicit_params = [arg.arg for arg in node.args.args]
        if node.args.vararg:
            explicit_params.append(node.args.vararg.arg)
        all_params = explicit_params + captures
        for param, pname in zip(func.args, all_params):
            alloca = self.builder.alloca(param.type, name=pname)
            self.builder.store(param, alloca)
            if pname in nonlocal_vars:
                # Mutable capture — param is a cell pointer (i8*)
                self.variables[pname] = (alloca, "cell")
            elif node.args.vararg and pname == node.args.vararg.arg:
                # *args parameter — it's a list pointer (i8*)
                self.variables[pname] = (alloca, "list:int")
            else:
                self.variables[pname] = (alloca, "int")

        self._emit_stmts(node.body)

        if not self.builder.block.is_terminated:
            if func.return_value.type == void:
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(i64, 0))

        self.function, self.builder, self.variables, self._loop_stack = saved

    def _emit_inline_lambda(self, node: ast.Lambda) -> ir.Value:
        """Compile an inline lambda and return function pointer as i64."""
        self._lambda_counter += 1
        name = f"__inline_lambda_{self._lambda_counter}"
        self._declare_lambda(name, node)
        info = self._user_functions[name]
        self._emit_lambda_body(info.func, node)
        # Return function pointer as i64
        return self.builder.ptrtoint(info.func, i64)

    def _infer_attr_type_from_init(self, cls_name: str, attr_name: str,
                                     class_parents: dict) -> str | None:
        """Infer the type of a class attribute from __init__ assignments.

        Walks the class's __init__ (and parents) looking for `self.attr = param`
        where the param's type is known from call-site analysis. Also detects
        direct constant assignments like `self.x = 0.0`.
        """
        # _csa_class_asts is populated at the start of _analyze_call_sites
        cls = cls_name
        while cls:
            call_types = self._call_site_param_types.get(cls, [])
            cls_node = self._csa_class_asts.get(cls)
            if cls_node:
                for method in cls_node.body:
                    if (isinstance(method, ast.FunctionDef)
                            and method.name == "__init__"):
                        params = [a.arg for a in method.args.args]
                        # Map call-site type indices to param names
                        typed_params: dict[str, str] = {}
                        for i, t in enumerate(call_types):
                            pi = i + 1  # skip self
                            if t and 0 <= pi < len(params):
                                typed_params[params[pi]] = t
                        # Check __init__ defaults for type info
                        defaults = method.args.defaults
                        for di, d in enumerate(defaults):
                            pidx = len(params) - len(defaults) + di
                            if isinstance(d, ast.Constant):
                                if isinstance(d.value, float):
                                    typed_params[params[pidx]] = "float"
                                elif isinstance(d.value, bool):
                                    typed_params[params[pidx]] = "bool"
                                elif isinstance(d.value, str):
                                    typed_params[params[pidx]] = "str"
                        # Walk body for self.attr = typed_value
                        for n in ast.walk(method):
                            if isinstance(n, ast.Assign):
                                for tgt in n.targets:
                                    if (isinstance(tgt, ast.Attribute)
                                            and isinstance(tgt.value, ast.Name)
                                            and tgt.value.id == "self"
                                            and tgt.attr == attr_name):
                                        # self.attr = param
                                        if (isinstance(n.value, ast.Name)
                                                and n.value.id in typed_params):
                                            return typed_params[n.value.id]
                                        # self.attr = float_constant
                                        if (isinstance(n.value, ast.Constant)
                                                and isinstance(n.value.value, float)):
                                            return "float"
                                        if (isinstance(n.value, ast.Constant)
                                                and isinstance(n.value.value, bool)):
                                            return "bool"
                                        if (isinstance(n.value, ast.Constant)
                                                and isinstance(n.value.value, str)):
                                            return "str"
            cls = class_parents.get(cls)
        return None

    def _needs_slot_names(self, tree: ast.Module) -> bool:
        """Determine whether the program uses any introspection feature
        that requires the runtime to know slot names.

        If nothing in the source uses name-based attribute access, we can
        skip registering slot names and omit the fallback lookup machinery.
        """
        INTROSPECTION_FUNCS = {"getattr", "setattr", "hasattr", "delattr",
                               "vars", "dir"}
        DUNDER_ATTRS = {"__dict__", "__slots__"}
        DUNDER_METHODS = {"__getattr__", "__setattr__", "__getattribute__"}
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id in INTROSPECTION_FUNCS):
                return True
            if isinstance(n, ast.Attribute) and n.attr in DUNDER_ATTRS:
                return True
            if (isinstance(n, ast.FunctionDef)
                    and n.name in DUNDER_METHODS):
                return True
        # Also: any obj.attr where we can't determine the class means
        # the compiler will fall back to name-based lookup.
        # We need to scope-check: function params can shadow module vars.
        known_classes: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                known_classes.add(n.name)

        def obj_vars_in_scope(scope_node: ast.AST) -> set[str]:
            """Variables in a scope that are assigned from ClassName(...)."""
            result: set[str] = set()
            for n in ast.walk(scope_node):
                if (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name)
                        and isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Name)
                        and n.value.func.id in known_classes):
                    result.add(n.targets[0].id)
            return result

        def check_scope(scope_node: ast.AST, is_func: bool = False) -> bool:
            """True if any obj.attr in this scope has an unknown-class receiver."""
            local_obj_vars = obj_vars_in_scope(scope_node)
            params: set[str] = set()
            if is_func and isinstance(scope_node, ast.FunctionDef):
                params = {a.arg for a in scope_node.args.args}
            # Walk only non-nested nodes (descend into nested fns separately)
            for n in ast.walk(scope_node):
                if (isinstance(n, ast.FunctionDef)
                        and n is not scope_node):
                    # Handle nested function separately — don't double-visit
                    if check_scope(n, is_func=True):
                        return True
                    continue
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                    name = n.value.id
                    if name == "self":
                        continue
                    if name in known_classes:
                        continue
                    if name in local_obj_vars:
                        continue
                    if name in params:
                        # Function parameter — class may be inferable via
                        # call-site analysis, but SAFE default is to assume
                        # we need slot names. (Cheap conservative check.)
                        return True
                    # Module-level unknown var
                    if is_func:
                        return True  # inside a function, can't know
                    return True
                # Non-Name receivers (Subscript, Call, Attribute chain,
                # etc.) usually mean the class isn't statically pinned —
                # e.g., `d["key"].attr`, `items[0].attr`, `f().attr`.
                # Conservatively register slot names in these cases.
                if isinstance(n, ast.Attribute) and not isinstance(n.value, ast.Name):
                    # Skip nested attr chain from self (handled by dedicated
                    # nested-attr tracking): self.obj_attr.inner_attr.
                    if (isinstance(n.value, ast.Attribute)
                            and isinstance(n.value.value, ast.Name)
                            and n.value.value.id == "self"):
                        continue
                    return True
            return False

        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if check_scope(node, is_func=True):
                    return True
            elif isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, ast.FunctionDef):
                        # Methods: receiver is usually self (handled), but
                        # obj.attr on non-self is the same concern.
                        if check_scope(member, is_func=True):
                            return True
        # Module-level: check direct attribute accesses
        if check_scope(tree):
            return True
        return False

    def _assign_attribute_slots(self, tree: ast.Module) -> None:
        """Scan all classes to collect every `self.attr` and `obj.attr` name
        used, and assign a fixed slot index per attribute for fast access.

        Inherited slots keep the parent's index (child's new slots start
        after parent's last slot). This means a method inherited from the
        parent can safely use slot N on a child instance.

        Attrs used via getattr/setattr with dynamic names fall through to
        the linear-scan dict — not covered here.
        """
        self._slot_names_needed = self._needs_slot_names(tree)
        # First pass: gather attr names per class from self.attr patterns
        raw_attrs: dict[str, list[str]] = {}
        class_parents: dict[str, str | None] = {}
        class_nodes: dict[str, ast.ClassDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                parent = (node.bases[0].id
                          if node.bases and isinstance(node.bases[0], ast.Name)
                          else None)
                class_parents[node.name] = parent
                class_nodes[node.name] = node
                raw_attrs.setdefault(node.name, [])

        for cls_name, cls_node in class_nodes.items():
            seen = set(raw_attrs[cls_name])
            for member in cls_node.body:
                if not isinstance(member, ast.FunctionDef):
                    continue
                for n in ast.walk(member):
                    # self.attr references (either read or store target)
                    if (isinstance(n, ast.Attribute)
                            and isinstance(n.value, ast.Name)
                            and n.value.id == "self"):
                        if n.attr not in seen:
                            seen.add(n.attr)
                            raw_attrs[cls_name].append(n.attr)

        # Second pass: also collect attrs accessed on instances (obj.attr where
        # obj is a known class instance). This catches patterns like outer
        # code doing `e.pos.x` even if no method of Entity uses `pos`.
        obj_var_class: dict[str, str] = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id in class_nodes):
                obj_var_class[node.targets[0].id] = node.value.func.id
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in obj_var_class):
                cls_name = obj_var_class[node.value.id]
                if node.attr not in raw_attrs.setdefault(cls_name, []):
                    raw_attrs[cls_name].append(node.attr)

        # Also collect secondary bases for multiple inheritance.
        class_all_bases: dict[str, list[str]] = {}
        for cls_name, cls_node in class_nodes.items():
            class_all_bases[cls_name] = [
                b.id for b in cls_node.bases
                if isinstance(b, ast.Name) and b.id in class_nodes
            ]

        # Third pass: compute final slot layout with parent inheritance.
        # Process classes in parent-before-child order.
        processed: set[str] = set()
        def assign(cls_name: str) -> None:
            if cls_name in processed:
                return
            parent = class_parents.get(cls_name)
            if parent and parent in class_nodes:
                assign(parent)
            # Also ensure secondary bases are processed first
            for base in class_all_bases.get(cls_name, [])[1:]:
                if base in class_nodes:
                    assign(base)
            slots: dict[str, int] = {}
            if parent and parent in self._class_attr_slots:
                slots.update(self._class_attr_slots[parent])
            # Inherit slots from secondary bases (multiple inheritance)
            for base in class_all_bases.get(cls_name, [])[1:]:
                if base in self._class_attr_slots:
                    for attr, _ in self._class_attr_slots[base].items():
                        if attr not in slots:
                            slots[attr] = len(slots)
            next_idx = len(slots)
            for attr in raw_attrs.get(cls_name, []):
                if attr not in slots:
                    slots[attr] = next_idx
                    next_idx += 1
            self._class_attr_slots[cls_name] = slots
            processed.add(cls_name)

        for cls_name in class_nodes:
            assign(cls_name)

    def _analyze_call_sites(self, tree: ast.Module) -> None:
        """Scan all call sites to determine argument types for each function."""
        # Save the module tree so other detectors (e.g. the class-attr
        # global scan) can walk it.
        self._csa_root_tree = tree
        # Build class inheritance map and cache class AST nodes
        class_parents: dict[str, str | None] = {}
        self._csa_class_asts: dict[str, ast.ClassDef] = {}
        func_asts: dict[str, ast.FunctionDef] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                parent = node.bases[0].id if node.bases and isinstance(node.bases[0], ast.Name) else None
                class_parents[node.name] = parent
                self._csa_class_asts[node.name] = node
            elif isinstance(node, ast.FunctionDef):
                # Track the first FunctionDef per name (module-level takes
                # precedence over nested; class methods tracked separately).
                func_asts.setdefault(node.name, node)

        # Build static variable type map from assignments
        var_types: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    if isinstance(node.value, ast.List):
                        if node.value.elts and isinstance(node.value.elts[0], (ast.List, ast.ListComp)):
                            var_types[tgt.id] = "list:list"
                        elif (node.value.elts
                              and all(isinstance(e, ast.Constant)
                                      and isinstance(e.value, str)
                                      for e in node.value.elts)):
                            var_types[tgt.id] = "list:str"
                        elif (node.value.elts
                              and all(isinstance(e, ast.Constant)
                                      and isinstance(e.value, float)
                                      for e in node.value.elts)):
                            var_types[tgt.id] = "list:float"
                        else:
                            var_types[tgt.id] = "list"
                    elif isinstance(node.value, ast.ListComp):
                        var_types[tgt.id] = "list"
                    elif isinstance(node.value, (ast.Dict, ast.DictComp)):
                        var_types[tgt.id] = "dict"
                    elif isinstance(node.value, ast.Set):
                        var_types[tgt.id] = "list"
                    elif isinstance(node.value, ast.Constant):
                        if isinstance(node.value.value, str):
                            var_types[tgt.id] = "str"
                        elif isinstance(node.value.value, float):
                            var_types[tgt.id] = "float"

        # Track variable → class name from assignments like `x = MyClass(...)`
        obj_classes: dict[str, str] = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id in class_parents):
                obj_classes[node.targets[0].id] = node.value.func.id

        # Iterative fixpoint: also track assignments from function calls
        # whose return type we've inferred as obj. Scan function defs to
        # find `return ClassName(...)` / `return var_assigned_from_Class()`
        # and propagate their target class to callers of that function.
        func_returns_cls: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Iteratively build local_obj: start with direct
            # ClassName(...) assignments, then propagate through Name-to-
            # Name assignments (x = y where y is a known obj).
            local_obj: dict[str, str] = {}
            for _ in range(5):  # fixpoint, usually 2-3 iterations max
                prev_size = len(local_obj)
                for n in ast.walk(node):
                    if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                            and isinstance(n.targets[0], ast.Name)):
                        continue
                    tgt = n.targets[0].id
                    if (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name)
                            and n.value.func.id in class_parents):
                        local_obj[tgt] = n.value.func.id
                    elif (isinstance(n.value, ast.Name)
                          and n.value.id in local_obj):
                        local_obj[tgt] = local_obj[n.value.id]
                if len(local_obj) == prev_size:
                    break
            for n in ast.walk(node):
                if isinstance(n, ast.Return) and n.value is not None:
                    if (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name)
                            and n.value.func.id in class_parents):
                        func_returns_cls[node.name] = n.value.func.id
                        break
                    if (isinstance(n.value, ast.Name)
                            and n.value.id in local_obj):
                        func_returns_cls[node.name] = local_obj[n.value.id]
                        break
        # Propagate to `var = func()` module-level assignments
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id in func_returns_cls):
                if node.targets[0].id not in obj_classes:
                    obj_classes[node.targets[0].id] = func_returns_cls[node.value.func.id]

        # Save for reuse by other passes (e.g. global class-attr scan).
        self._csa_obj_classes = dict(obj_classes)

        # Register object instances in var_types so call-site analysis knows
        # when a class instance is passed as a function argument.
        for vname in obj_classes:
            var_types[vname] = "obj"

        # Track constructor arg classes: when ClassName(var, ...) is called
        # and var is a known object instance, record that arg index → class.
        # Used by _detect_class_container_attrs to build obj_attr_types.
        self._csa_constructor_arg_classes: dict[str, dict[int, str]] = {}
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id in class_parents):
                cls_called = n.func.id
                for arg_idx, arg in enumerate(n.args):
                    arg_cls = None
                    # Case 1: arg is a known object variable
                    if isinstance(arg, ast.Name) and arg.id in obj_classes:
                        arg_cls = obj_classes[arg.id]
                    # Case 2: arg is a constructor call ClassName(...)
                    elif (isinstance(arg, ast.Call)
                            and isinstance(arg.func, ast.Name)
                            and arg.func.id in class_parents):
                        arg_cls = arg.func.id
                    if arg_cls:
                        if cls_called not in self._csa_constructor_arg_classes:
                            self._csa_constructor_arg_classes[cls_called] = {}
                        self._csa_constructor_arg_classes[cls_called][arg_idx] = arg_cls

        # Track obj-param classes per function. `_csa_func_param_classes`
        # maps func_name -> {param_idx: class_name}. Used in
        # `_emit_function_def` to tag obj params with their specific class
        # so `self.variables[param].class` resolves correctly for downstream
        # `x.attr` accesses.
        self._csa_func_param_classes: dict[str, dict[int, str]] = {}
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)):
                continue
            fn_name = n.func.id
            # Skip class constructors (already handled above); we care about
            # regular user functions and class methods invoked as obj.m(x).
            for arg_idx, arg in enumerate(n.args):
                arg_cls = None
                if isinstance(arg, ast.Name) and arg.id in obj_classes:
                    arg_cls = obj_classes[arg.id]
                elif (isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Name)
                        and arg.func.id in class_parents):
                    arg_cls = arg.func.id
                if arg_cls:
                    self._csa_func_param_classes.setdefault(
                        fn_name, {})[arg_idx] = arg_cls

        # Track loop variable types from for-in iterables
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                varname = node.target.id
                it = node.iter
                # for x in [1.0, 2.0] → x is float
                if isinstance(it, ast.List) and it.elts:
                    if all(isinstance(e, ast.Constant) and isinstance(e.value, float)
                           for e in it.elts):
                        var_types[varname] = "float"
                    elif all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                             for e in it.elts):
                        var_types[varname] = "str"
                # for x in list_var → x gets the list's element type
                elif isinstance(it, ast.Name) and it.id in var_types:
                    vt = var_types[it.id]
                    if vt == "str":
                        var_types[varname] = "str"
                    elif vt == "list:str":
                        var_types[varname] = "str"
                    elif vt == "list:float":
                        var_types[varname] = "float"

        # Refine dict value types from subscript assignments: d[k] = {}
        # This lets call-site analysis propagate "dict:dict" (or dict:list,
        # dict:str) to function parameters, so nested subscripts work.
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Subscript)
                    and isinstance(node.targets[0].value, ast.Name)):
                base = node.targets[0].value.id
                if base in var_types and var_types[base].startswith("dict"):
                    if isinstance(node.value, (ast.Dict, ast.DictComp)):
                        var_types[base] = "dict:dict"
                    elif isinstance(node.value, (ast.List, ast.ListComp)):
                        var_types[base] = "dict:list"

        # Also detect dict value types inside function bodies: when a function
        # parameter d has d[k] = {...} / d[k] = [...], record the refined type
        # so it propagates when the function is called with a dict argument.
        func_param_dict_refinements: dict[str, dict[str, str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            params = {arg.arg for arg in node.args.args}
            for n in ast.walk(node):
                if (isinstance(n, ast.Assign)
                        and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Subscript)
                        and isinstance(n.targets[0].value, ast.Name)
                        and n.targets[0].value.id in params):
                    pname = n.targets[0].value.id
                    if isinstance(n.value, (ast.Dict, ast.DictComp)):
                        func_param_dict_refinements.setdefault(
                            node.name, {})[pname] = "dict:dict"
                    elif isinstance(n.value, (ast.List, ast.ListComp)):
                        func_param_dict_refinements.setdefault(
                            node.name, {})[pname] = "dict:list"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Direct function/class calls: func(args)
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            # Method calls: obj.method(args) — register under "Class.method"
            # if the object's class is known, otherwise under bare "method".
            elif isinstance(node.func, ast.Attribute):
                method_name = node.func.attr
                cls_name = None
                if (isinstance(node.func.value, ast.Name)
                        and node.func.value.id in obj_classes):
                    cls_name = obj_classes[node.func.value.id]
                func_name = f"{cls_name}.{method_name}" if cls_name else method_name
            else:
                continue

            # Determine type of each argument from AST
            arg_types: list[str | None] = []
            for arg in node.args:
                # Check if arg is a variable with known type
                if isinstance(arg, ast.Name) and arg.id in var_types:
                    arg_types.append(var_types[arg.id])
                elif isinstance(arg, ast.Constant):
                    if isinstance(arg.value, str):
                        arg_types.append("str")
                    elif isinstance(arg.value, bool):
                        # Check bool before int (bool is subclass of int)
                        arg_types.append("bool")
                    elif isinstance(arg.value, float):
                        arg_types.append("float")
                    elif isinstance(arg.value, int):
                        arg_types.append("int")
                    else:
                        arg_types.append(None)
                elif (isinstance(arg, ast.UnaryOp)
                      and isinstance(arg.op, ast.USub)
                      and isinstance(arg.operand, ast.Constant)):
                    # Negative literals: -2.0, -3, etc.
                    if isinstance(arg.operand.value, float):
                        arg_types.append("float")
                    elif isinstance(arg.operand.value, int):
                        arg_types.append("int")
                    else:
                        arg_types.append(None)
                elif isinstance(arg, ast.JoinedStr):
                    arg_types.append("str")
                elif isinstance(arg, ast.List):
                    # Detect nested lists (list of lists)
                    if arg.elts and isinstance(arg.elts[0], (ast.List, ast.ListComp)):
                        arg_types.append("list:list")
                    elif arg.elts and isinstance(arg.elts[0], ast.Constant) and isinstance(arg.elts[0].value, str):
                        arg_types.append("list:str")
                    else:
                        arg_types.append("list")
                elif isinstance(arg, ast.Dict):
                    # Refine the dict tag with its value type when the literal
                    # has uniform values — propagates so callee's d[k] can
                    # unwrap to the correct bare LLVM type.
                    if arg.values and all(
                            isinstance(v, ast.Constant)
                            and isinstance(v.value, int)
                            and not isinstance(v.value, bool)
                            for v in arg.values):
                        arg_types.append("dict:int")
                    elif arg.values and all(
                            isinstance(v, ast.Constant)
                            and isinstance(v.value, str)
                            for v in arg.values):
                        arg_types.append("dict:str")
                    elif arg.values and all(
                            isinstance(v, (ast.List, ast.ListComp))
                            for v in arg.values):
                        arg_types.append("dict:list")
                    elif arg.values and all(
                            isinstance(v, (ast.Dict, ast.DictComp))
                            for v in arg.values):
                        arg_types.append("dict:dict")
                    else:
                        arg_types.append("dict")
                elif (isinstance(arg, ast.Attribute)
                      and isinstance(arg.value, ast.Name)
                      and arg.value.id in obj_classes):
                    # obj.attr — infer type from class attribute analysis
                    cls = obj_classes[arg.value.id]
                    attr_type = self._infer_attr_type_from_init(
                        cls, arg.attr, class_parents)
                    arg_types.append(attr_type)
                elif (isinstance(arg, ast.Call)
                      and isinstance(arg.func, ast.Name)
                      and arg.func.id in class_parents):
                    # ClassName(...) — constructor call, arg is that class
                    arg_types.append("obj")
                else:
                    # Check if expression contains float constants (e.g. 2.0 * 3.0)
                    # but NOT if it contains a class constructor (those would
                    # falsely flag the outer as float due to inner float args)
                    has_ctor = any(
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id in class_parents
                        for sub in ast.walk(arg))
                    if has_ctor:
                        arg_types.append(None)
                    else:
                        has_float = any(
                            isinstance(sub, ast.Constant) and isinstance(sub.value, float)
                            for sub in ast.walk(arg))
                        arg_types.append("float" if has_float else None)

            # Propagate dict value type refinements from function bodies
            # to call-site arguments: if update_nested(data, ...) and the
            # function's first param gets d[k] = {}, refine var_types["data"].
            if func_name in func_param_dict_refinements:
                refinements = func_param_dict_refinements[func_name]
                # Map from function param names to arg index
                # We need the function's param names — find the FunctionDef
                for fn_node in ast.walk(tree):
                    if (isinstance(fn_node, ast.FunctionDef)
                            and fn_node.name == func_name):
                        fn_params = [a.arg for a in fn_node.args.args]
                        for pi, pname in enumerate(fn_params):
                            if (pname in refinements
                                    and pi < len(node.args)
                                    and isinstance(node.args[pi], ast.Name)):
                                caller_var = node.args[pi].id
                                if (caller_var in var_types
                                        and var_types[caller_var] == "dict"):
                                    var_types[caller_var] = refinements[pname]
                                    arg_types[pi] = refinements[pname]
                        break

            # Register for the function/class and its parent chain
            names_to_register = [func_name]
            # If func_name is a class, also register for parent classes
            # (since subclass constructor calls dispatch to parent __init__)
            parent = class_parents.get(func_name)
            while parent:
                names_to_register.append(parent)
                parent = class_parents.get(parent)
            # For method calls "Class.method", also register under parent
            # class names (since inherited methods are defined on the parent).
            if "." in func_name:
                cls_part, method_part = func_name.split(".", 1)
                parent = class_parents.get(cls_part)
                while parent:
                    names_to_register.append(f"{parent}.{method_part}")
                    parent = class_parents.get(parent)

            # Track distinct call signatures per function for monomorphization.
            # When a function is called with different scalar type signatures
            # (e.g., f(5) and f(1.5)), we'll generate separate specializations.
            #
            # Extend arg_types with kw args mapped to their positional slots,
            # so sig reflects ALL args the callee will see (not just the
            # positional ones). This is essential for correct monomorphization
            # when calls mix positional and keyword args:
            #   f(2.5, factor=4.0)  →  ("float", "float") not just ("float",)
            sig_arg_types = list(arg_types)
            if node.keywords and func_name in func_asts:
                fn_def = func_asts[func_name]
                fn_params = [a.arg for a in fn_def.args.args]
                fn_params += [a.arg for a in fn_def.args.kwonlyargs]
                while len(sig_arg_types) < len(fn_params):
                    sig_arg_types.append(None)
                for kw in node.keywords:
                    if kw.arg is None or kw.arg not in fn_params:
                        continue
                    pi = fn_params.index(kw.arg)
                    if pi >= len(sig_arg_types):
                        continue
                    kw_type: str | None = None
                    if isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, bool):
                            kw_type = "bool"
                        elif isinstance(kw.value.value, float):
                            kw_type = "float"
                        elif isinstance(kw.value.value, int):
                            kw_type = "int"
                        elif isinstance(kw.value.value, str):
                            kw_type = "str"
                    elif (isinstance(kw.value, ast.UnaryOp)
                          and isinstance(kw.value.op, ast.USub)
                          and isinstance(kw.value.operand, ast.Constant)):
                        if isinstance(kw.value.operand.value, float):
                            kw_type = "float"
                        elif isinstance(kw.value.operand.value, int):
                            kw_type = "int"
                    elif isinstance(kw.value, ast.Name) and kw.value.id in var_types:
                        kw_type = var_types[kw.value.id]
                    if kw_type is not None:
                        sig_arg_types[pi] = kw_type
            sig = tuple(sig_arg_types)
            for name in names_to_register:
                sigs = self._function_signatures.setdefault(name, [])
                if sig not in sigs:
                    sigs.append(sig)

            for name in names_to_register:
                if name not in self._call_site_param_types:
                    self._call_site_param_types[name] = list(arg_types)
                else:
                    existing = self._call_site_param_types[name]
                    # Extend when a later call provides more args (e.g. first
                    # call uses defaults, second provides explicit values).
                    for i in range(len(existing), len(arg_types)):
                        existing.append(arg_types[i])
                    for i in range(min(len(existing), len(arg_types))):
                        if existing[i] == "mixed":
                            continue  # already mixed, can't refine further
                        if arg_types[i] is None:
                            continue  # unknown doesn't override known
                        if existing[i] is None:
                            existing[i] = arg_types[i]  # first known type
                            continue
                        if arg_types[i] == existing[i]:
                            continue  # same type, no conflict
                        # Types conflict — check if it's a safe refinement
                        # or a genuine conflict requiring "mixed"
                        if (arg_types[i].startswith("list:") and existing[i] == "list"):
                            existing[i] = arg_types[i]  # refine list element type
                        elif (existing[i].startswith("list:") and arg_types[i] == "list"):
                            pass  # keep the more specific type
                        elif (arg_types[i] == "bool" and existing[i] == "int"):
                            pass  # bool is a subtype of int, keep int
                        elif (existing[i] == "bool" and arg_types[i] == "int"):
                            existing[i] = "int"  # widen to int
                        else:
                            # Genuine type conflict (e.g. int vs str)
                            existing[i] = "mixed"

        # Store refined module-level dict value types so codegen can
        # populate _dict_var_dict_values for nested subscript handling.
        for vname, vtype in var_types.items():
            if vtype == "dict:dict":
                self._dict_var_dict_values.add(vname)
            elif vtype == "dict:list":
                self._dict_var_list_values.add(vname)
            elif vtype == "dict:int":
                self._dict_var_int_values.add(vname)

        # Propagate signatures through the call graph: when function F is
        # called inside G's body with G's parameter as an argument, F needs a
        # signature per G-signature. Iterate until no new sigs are added.
        # This ensures `inner(y)` inside a monomorphized `outer(y)` gets the
        # right specialization of inner at each call site.
        #
        # Also include class methods: a method call `compute(self.val)` where
        # self.val's type is known from __init__ should propagate that type
        # as the callee's arg sig.
        propagate_scopes: list[tuple[str | None, ast.FunctionDef]] = []
        for name, fn in func_asts.items():
            propagate_scopes.append((None, fn))
        for cls_name, cls_node in self._csa_class_asts.items():
            for item in cls_node.body:
                if isinstance(item, ast.FunctionDef):
                    propagate_scopes.append((cls_name, item))
        changed = True
        iterations = 0
        while changed and iterations < 10:
            iterations += 1
            changed = False
            for owner_cls, caller_ast in propagate_scopes:
                caller_name = caller_ast.name
                # For methods, use "Class.method" as the key to match how
                # _analyze_call_sites registers method sigs.
                caller_key = (f"{owner_cls}.{caller_name}"
                              if owner_cls else caller_name)
                caller_sigs = self._function_signatures.get(caller_key, [])
                if not caller_sigs:
                    continue
                # For methods, self is the first param (skip it).
                caller_params = [a.arg for a in caller_ast.args.args]
                caller_params += [a.arg for a in caller_ast.args.kwonlyargs]
                is_method = owner_cls is not None
                for caller_sig in list(caller_sigs):
                    # Build the set of param → type for this signature
                    param_type_of: dict[str, str] = {}
                    for pi, pt in enumerate(caller_sig):
                        if pi < len(caller_params) and pt is not None:
                            param_type_of[caller_params[pi]] = pt
                    # For methods, self.attr types add useful info even
                    # when caller's param types are empty; skip only if
                    # there's no info at all.
                    if not param_type_of and not is_method:
                        continue
                    # Walk calls inside caller's body
                    for n in ast.walk(caller_ast):
                        if not (isinstance(n, ast.Call)
                                and isinstance(n.func, ast.Name)):
                            continue
                        callee = n.func.id
                        if callee not in self._function_signatures:
                            continue
                        if callee == caller_name:
                            continue  # self-recursion handled elsewhere
                        # Build callee sig by substituting caller's param
                        # types into the call's args. Also resolve self.attr
                        # references for method callers via
                        # _infer_attr_type_from_init.
                        def _arg_type(arg: ast.expr) -> str | None:
                            if (isinstance(arg, ast.Name)
                                    and arg.id in param_type_of):
                                return param_type_of[arg.id]
                            if isinstance(arg, ast.Constant):
                                v = arg.value
                                if isinstance(v, bool):
                                    return "bool"
                                if isinstance(v, float):
                                    return "float"
                                if isinstance(v, int):
                                    return "int"
                                if isinstance(v, str):
                                    return "str"
                                return None
                            if (is_method
                                    and isinstance(arg, ast.Attribute)
                                    and isinstance(arg.value, ast.Name)
                                    and arg.value.id == "self"):
                                return self._infer_attr_type_from_init(
                                    owner_cls, arg.attr, class_parents)
                            if (isinstance(arg, ast.BinOp)
                                    and isinstance(arg.op, (ast.Add, ast.Sub,
                                                            ast.Mult, ast.Div))):
                                has_float = False
                                for sub in ast.walk(arg):
                                    t: str | None = None
                                    if (isinstance(sub, ast.Name)
                                            and sub.id in param_type_of):
                                        t = param_type_of[sub.id]
                                    elif (is_method
                                          and isinstance(sub, ast.Attribute)
                                          and isinstance(sub.value, ast.Name)
                                          and sub.value.id == "self"):
                                        t = self._infer_attr_type_from_init(
                                            owner_cls, sub.attr, class_parents)
                                    elif (isinstance(sub, ast.Constant)
                                          and isinstance(sub.value, float)):
                                        t = "float"
                                    if t == "float":
                                        has_float = True
                                        break
                                if isinstance(arg.op, ast.Div) or has_float:
                                    return "float"
                                return "int"
                            return None

                        callee_sig: list[str | None] = []
                        for arg in n.args:
                            callee_sig.append(_arg_type(arg))
                        # Also account for keyword args in the call
                        if n.keywords and callee in func_asts:
                            callee_def = func_asts[callee]
                            callee_params = [
                                a.arg for a in callee_def.args.args]
                            callee_params += [
                                a.arg for a in callee_def.args.kwonlyargs]
                            while len(callee_sig) < len(callee_params):
                                callee_sig.append(None)
                            for kw in n.keywords:
                                if (kw.arg is None
                                        or kw.arg not in callee_params):
                                    continue
                                pi = callee_params.index(kw.arg)
                                if pi >= len(callee_sig):
                                    continue
                                kt = _arg_type(kw.value)
                                if kt is not None:
                                    callee_sig[pi] = kt
                        new_sig = tuple(callee_sig)
                        if new_sig not in self._function_signatures[callee]:
                            self._function_signatures[callee].append(new_sig)
                            changed = True
                        # Also merge into _call_site_param_types so the
                        # non-monomorphization path still sees the right
                        # param types for functions without scalar conflicts.
                        existing = self._call_site_param_types.setdefault(
                            callee, [])
                        for i, t in enumerate(callee_sig):
                            if t is None:
                                continue
                            while len(existing) <= i:
                                existing.append(None)
                            if existing[i] is None:
                                existing[i] = t
                                changed = True
                            elif existing[i] != t:
                                # Compatible bool/int? leave as int.
                                if {existing[i], t} == {"int", "bool"}:
                                    existing[i] = "int"
                                elif existing[i] == "mixed":
                                    pass  # keep mixed
                                else:
                                    # Genuine conflict → "mixed" (will be
                                    # handled by monomorphization pass).
                                    existing[i] = "mixed"

        # Register __setitem__ call-site types from `obj[key] = val` patterns.
        # This lets the method body know the param types (str key, int val, etc.)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Subscript)
                    and isinstance(node.targets[0].value, ast.Name)):
                obj_name = node.targets[0].value.id
                if obj_name in obj_classes:
                    cls_name = obj_classes[obj_name]
                    key_type = self._infer_call_arg_type(node.targets[0].slice)
                    val_type = self._infer_call_arg_type(node.value)
                    qkey = f"{cls_name}.__setitem__"
                    existing = self._call_site_param_types.get(qkey)
                    types = [key_type, val_type]
                    if existing is None:
                        self._call_site_param_types[qkey] = types
                    # Also register under bare name for fallback
                    if "__setitem__" not in self._call_site_param_types:
                        self._call_site_param_types["__setitem__"] = types

        # Trace sorted(list, key=func) / min/max(list, key=func) to populate
        # call-site types for the key function. The key function receives
        # elements of the list, so its param type matches the list's elem type.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name)
                    and node.func.id in ("sorted", "min", "max")):
                continue
            key_func_name = None
            for kw in node.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Name):
                    key_func_name = kw.value.id
            if key_func_name is None or key_func_name not in func_asts:
                continue
            # Determine the list's element type
            if node.args:
                list_node = node.args[0]
                elem_type = None
                if isinstance(list_node, ast.List) and list_node.elts:
                    if all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                           for e in list_node.elts):
                        elem_type = "str"
                elif isinstance(list_node, ast.Name) and list_node.id in var_types:
                    vt = var_types[list_node.id]
                    if vt == "list:str":
                        elem_type = "str"
                if elem_type is not None:
                    existing = self._call_site_param_types.setdefault(
                        key_func_name, [])
                    if not existing:
                        existing.append(elem_type)
                    elif existing[0] is None:
                        existing[0] = elem_type

    def _declare_lambda(self, var_name: str, lam: ast.Lambda) -> None:
        """Create a hidden function for a lambda assigned to a variable."""
        param_names = [arg.arg for arg in lam.args.args]
        param_types = [i64] * len(param_names)
        ret_type = i64  # lambdas return a value

        # Check for float/string in body
        for sub in ast.walk(lam.body):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, float):
                ret_type = double
                break
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                ret_type = i8_ptr
                break

        func_type = ir.FunctionType(ret_type, param_types)
        fn_name = f"fastpy.lambda.{var_name}"
        func = ir.Function(self.module, func_type, name=fn_name)

        for param, pname in zip(func.args, param_names):
            param.name = pname

        ret_tag = "float" if ret_type == double else ("str" if ret_type == i8_ptr else "int")
        defaults = lam.args.defaults
        self._user_functions[var_name] = FuncInfo(
            func=func,
            ret_tag=ret_tag,
            param_count=len(param_names),
            defaults=defaults,
            min_args=len(param_names) - len(defaults),
        )

    def _emit_lambda_body(self, func: ir.Function, lam: ast.Lambda) -> None:
        """Generate code for a lambda's body (single expression)."""
        saved = (self.function, self.builder, self.variables, self._loop_stack)

        self.function = func
        entry = func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self._loop_stack = []

        # Store parameters
        params = [arg.arg for arg in lam.args.args]
        for param, pname in zip(func.args, params):
            alloca = self.builder.alloca(param.type, name=pname)
            self.builder.store(param, alloca)
            self.variables[pname] = (alloca, "int")

        # Evaluate body and return
        result = self._emit_expr_value(lam.body)
        expected_ret = func.return_value.type
        if result.type != expected_ret:
            if isinstance(expected_ret, ir.IntType) and isinstance(result.type, ir.DoubleType):
                result = self.builder.fptosi(result, expected_ret)
            elif isinstance(expected_ret, ir.DoubleType) and isinstance(result.type, ir.IntType):
                result = self.builder.sitofp(result, expected_ret)
        self.builder.ret(result)

        self.function, self.builder, self.variables, self._loop_stack = saved

    def _signature_scalar_conflict(self, sigs: list[tuple]) -> bool:
        """True if two signatures differ in scalar (int/float/bool) types
        at the same position — which would force "mixed" behavior and need
        monomorphization to handle correctly.
        """
        if len(sigs) < 2:
            return False
        # For each position, collect the distinct scalar types seen
        SCALARS = {"int", "float", "bool"}
        max_len = max(len(s) for s in sigs)
        for i in range(max_len):
            seen: set[str] = set()
            for s in sigs:
                if i < len(s) and s[i] in SCALARS:
                    seen.add(s[i])
            # Ignore bool-vs-int (compatible)
            if seen == {"int", "bool"} or seen == {"bool", "int"}:
                seen = {"int"}
            if len(seen) > 1:
                return True
        return False

    def _mangle_sig(self, sig: tuple) -> str:
        """Encode a signature into a short suffix for specialized function names."""
        parts = []
        for t in sig:
            if t == "int":
                parts.append("i")
            elif t == "float":
                parts.append("d")
            elif t == "bool":
                parts.append("b")
            elif t == "str":
                parts.append("s")
            elif t == "obj":
                parts.append("o")
            elif t is None:
                parts.append("x")
            else:
                # list:str, dict:int, etc. — encode as first letter + subtype
                parts.append(t.replace(":", ""))
        return "_".join(parts) if parts else "void"

    def _resolve_class_specialization(self, class_name: str, arg_nodes: list,
                                       keyword_nodes: list | None = None) -> str:
        """Given a constructor call's args, pick the matching class variant,
        or return class_name unchanged if not monomorphized.
        """
        specs = self._monomorphized_classes.get(class_name)
        if not specs:
            return class_name
        # Infer types at the call site
        call_sig = list(self._infer_call_arg_type(a) for a in arg_nodes)
        # Map keyword args using __init__'s parameters (skip self).
        if keyword_nodes:
            cls_node = self._csa_class_asts.get(class_name)
            if cls_node is not None:
                init_def = None
                for item in cls_node.body:
                    if (isinstance(item, ast.FunctionDef)
                            and item.name == "__init__"):
                        init_def = item
                        break
                if init_def is not None:
                    init_params = [a.arg for a in init_def.args.args[1:]]  # skip self
                    init_params += [a.arg for a in init_def.args.kwonlyargs]
                    while len(call_sig) < len(init_params):
                        call_sig.append(None)
                    for kw in keyword_nodes:
                        if kw.arg is None or kw.arg not in init_params:
                            continue
                        pi = init_params.index(kw.arg)
                        if pi < len(call_sig):
                            call_sig[pi] = self._infer_call_arg_type(kw.value)
        call_sig_t = tuple(call_sig)
        for sig in specs:
            if call_sig_t == sig:
                return f"{class_name}__{self._mangle_sig(sig)}"
        for sig in specs:
            matches = True
            for i, (ct, st) in enumerate(zip(call_sig_t, sig)):
                if ct is None or st is None:
                    continue
                if ct != st:
                    if {ct, st} == {"bool", "int"}:
                        continue
                    matches = False
                    break
            if matches:
                return f"{class_name}__{self._mangle_sig(sig)}"
        return f"{class_name}__{self._mangle_sig(specs[0])}"

    def _resolve_specialization(self, func_name: str, arg_nodes: list,
                                keyword_nodes: list | None = None) -> str:
        """Given a call's arg AST nodes (and optional keyword args), return
        the mangled name of the matching specialization, or func_name if no
        monomorphization.
        """
        specs = self._monomorphized.get(func_name)
        if not specs:
            return func_name
        # Infer types at the call site for positional args
        call_sig = list(self._infer_call_arg_type(a) for a in arg_nodes)
        # Map keyword args to positional slots using the function's AST so
        # the call sig reflects all arguments the callee will see.
        if keyword_nodes:
            fn_def = getattr(self, '_function_def_nodes', {}).get(func_name)
            if fn_def is not None:
                fn_params = [a.arg for a in fn_def.args.args]
                fn_params += [a.arg for a in fn_def.args.kwonlyargs]
                while len(call_sig) < len(fn_params):
                    call_sig.append(None)
                for kw in keyword_nodes:
                    if kw.arg is None or kw.arg not in fn_params:
                        continue
                    pi = fn_params.index(kw.arg)
                    if pi < len(call_sig):
                        call_sig[pi] = self._infer_call_arg_type(kw.value)
        call_sig_t = tuple(call_sig)
        # Find best match (exact first, else look for a signature that
        # agrees on scalar types)
        for sig in specs:
            if call_sig_t == sig:
                return f"{func_name}__{self._mangle_sig(sig)}"
        # Partial match — match scalar positions
        for sig in specs:
            matches = True
            for i, (ct, st) in enumerate(zip(call_sig_t, sig)):
                if ct is None or st is None:
                    continue
                if ct != st:
                    # bool/int compatible
                    if {ct, st} == {"bool", "int"}:
                        continue
                    matches = False
                    break
            if matches:
                return f"{func_name}__{self._mangle_sig(sig)}"
        # Fall back to first spec
        return f"{func_name}__{self._mangle_sig(specs[0])}"

    def _infer_call_arg_type(self, node: ast.expr) -> str | None:
        """Best-effort type inference for a single call arg."""
        if isinstance(node, ast.Constant):
            if node.value is None:
                # None is passed where an object is expected (e.g.,
                # `Tree(5, None, None)` for nullable child pointers).
                # Tag as "obj" so the method body sees `call_tag="obj"`
                # and emits a runtime None check on the i64 param.
                return "obj"
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, str):
                return "str"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            if isinstance(node.operand, ast.Constant):
                if isinstance(node.operand.value, float):
                    return "float"
                if isinstance(node.operand.value, int):
                    return "int"
            # Unary minus on something typed — inherit the operand's type.
            return self._infer_call_arg_type(node.operand)
        if isinstance(node, ast.Name):
            if node.id in self.variables:
                _, tag = self.variables[node.id]
                if tag in ("int", "float", "str", "bool", "obj"):
                    return tag
                if tag.startswith("list"):
                    return tag
                if tag == "dict":
                    return "dict"
        # Attribute access: resolve via the owning class's attr-type sets.
        # This lets `compute(self.val)` monomorphize correctly when val is
        # a known-typed attr (float/bool/string/list/dict/obj).
        if isinstance(node, ast.Attribute):
            cls_name = self._infer_object_class(node.value)
            if cls_name:
                if node.attr in self._per_class_float_attrs.get(cls_name, set()):
                    return "float"
                if node.attr in getattr(self, "_class_bool_attrs", set()):
                    return "bool"
                if node.attr in getattr(self, "_class_string_attrs", set()):
                    return "str"
                # Obj-typed attr (tracked per-class)
                obj_types = self._class_obj_attr_types.get(cls_name, {})
                if node.attr in obj_types:
                    return "obj"
                # Default: assume int (slot-typed attrs that aren't
                # float/bool/string/obj are typically ints).
                return "int"
        # Binary arithmetic: result is float if either side is float;
        # Div always returns float; otherwise inherit int-ness.
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                return "float"
            lt = self._infer_call_arg_type(node.left)
            rt = self._infer_call_arg_type(node.right)
            if lt == "float" or rt == "float":
                return "float"
            if lt == "str" or rt == "str":
                return "str"
            scalars = {"int", "bool"}
            if lt in scalars and (rt in scalars or rt is None):
                return "int"
            if rt in scalars and (lt in scalars or lt is None):
                return "int"
        # Comparisons and boolean ops — result is bool
        if isinstance(node, ast.Compare):
            return "bool"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return "bool"
        # Self-recursive or other user function calls — best-effort lookup.
        # This is the key case for recursive monomorphized functions: f(x - 1)
        # inside f's body should resolve to the same specialization we're in.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            if fname in self._user_functions:
                info = self._user_functions[fname]
                if info.ret_tag == "float":
                    return "float"
                if info.ret_tag == "int":
                    return "int"
                if info.ret_tag == "bool":
                    return "bool"
                if info.ret_tag == "str":
                    return "str"
        # Float-containing expression
        has_float = any(
            isinstance(sub, ast.Constant) and isinstance(sub.value, float)
            for sub in ast.walk(node))
        if has_float:
            return "float"
        return None

    def _declare_user_function(self, node: ast.FunctionDef,
                               _sig_override: list | None = None,
                               _name_override: str | None = None) -> None:
        """Forward-declare a user function.

        When _sig_override / _name_override are provided, emit a monomorphized
        specialization with the supplied argument types and key it under the
        overridden name in self._user_functions. When they are None and the
        function has scalar-conflicting call signatures, recursively declare
        one specialization per signature and register them in
        self._monomorphized.
        """
        # Check for monomorphization (only on top-level declaration pass)
        if _sig_override is None and _name_override is None:
            if node.name in self._user_functions:
                return
            sigs = self._function_signatures.get(node.name, [])
            # Monomorphize only for non-vararg/kwarg functions where scalar
            # types differ across call sites.
            is_special = (node.args.vararg is not None
                          or node.args.kwarg is not None)
            if (not is_special
                    and self._signature_scalar_conflict(sigs)):
                self._monomorphized[node.name] = list(sigs)
                for sig in sigs:
                    mangled = f"{node.name}__{self._mangle_sig(sig)}"
                    self._declare_user_function(
                        node, _sig_override=list(sig),
                        _name_override=mangled)
                # Register the original name as an alias pointing to the
                # first specialization's FuncInfo. This keeps "name in
                # self._user_functions" true for code that predates
                # monomorphization-aware dispatch. The actual call sites
                # resolve to the correct specialization via
                # _resolve_specialization before calling.
                first_mangled = f"{node.name}__{self._mangle_sig(sigs[0])}"
                if first_mangled in self._user_functions:
                    self._user_functions[node.name] = self._user_functions[first_mangled]
                    self._function_def_nodes[node.name] = node
                return
        else:
            # Specialization path: skip if already declared under this name
            key_name = _name_override if _name_override else node.name
            if key_name in self._user_functions:
                return

        has_vararg = node.args.vararg is not None
        has_kwarg = node.args.kwarg is not None
        returns_param = False
        call_types: list = []

        if has_vararg and not node.args.args:
            param_names = [node.args.vararg.arg]
            param_types = [i8_ptr]
            # Check if function returns the *args parameter itself
            for n in ast.walk(node):
                if isinstance(n, ast.Return) and isinstance(n.value, ast.Name):
                    if n.value.id == node.args.vararg.arg:
                        returns_param = True
        elif has_kwarg and not node.args.args:
            param_names = [node.args.kwarg.arg]
            param_types = [i8_ptr]
            for n in ast.walk(node):
                if isinstance(n, ast.Return) and isinstance(n.value, ast.Name):
                    if n.value.id == node.args.kwarg.arg:
                        returns_param = True
        else:
            # Combine positional args + keyword-only args into the function's
            # parameter list. Call sites enforce that kwonly args must be
            # passed as keywords (handled in _emit_user_call's kwarg logic).
            param_names = [arg.arg for arg in node.args.args]
            param_names += [arg.arg for arg in node.args.kwonlyargs]
            # Use call-site analysis to determine param types.
            # When a specialization override is given, use it directly
            # (bypasses the "mixed" merge for scalar types).
            if _sig_override is not None:
                call_types = list(_sig_override)
                # Pad with None for any trailing params not covered by the sig.
                while len(call_types) < len(param_names):
                    call_types.append(None)
            else:
                call_types = self._call_site_param_types.get(node.name, [])
            # Also detect string params via AST heuristic (used where call-site
            # analysis is silent — e.g., param only provided via default).
            string_params_by_heuristic = self._detect_string_params(node)
            param_types = []
            for i, pname in enumerate(param_names):
                # Call-site analysis has priority over the string heuristic:
                # if we know the caller passes int, respect that even if the
                # param is used in an f-string (where it'd be int_to_str'd).
                if i < len(call_types) and call_types[i] is not None:
                    ct = call_types[i]
                    if (ct in ("str", "list", "dict", "obj")
                            or ct.startswith("list:")
                            or ct.startswith("dict:")):
                        param_types.append(i8_ptr)
                    elif ct == "float":
                        param_types.append(double)
                    else:
                        param_types.append(i64)
                elif pname in string_params_by_heuristic:
                    param_types.append(i8_ptr)
                else:
                    param_types.append(i64)

        ret_type = i8_ptr if returns_param else i64

        # Only scan returns in THIS function, not nested defs.
        _nested_ids = set()
        for _item in ast.walk(node):
            if _item is not node and isinstance(_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for _sub in ast.walk(_item):
                    _nested_ids.add(id(_sub))
        has_return_value = any(
            isinstance(n, ast.Return) and n.value is not None
            for n in ast.walk(node)
            if id(n) not in _nested_ids
        )
        # Pre-collect string variables for return type detection
        str_vars = set()
        obj_vars: set[str] = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name):
                        if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                            str_vars.add(tgt.id)
                        elif isinstance(n.value, ast.JoinedStr):
                            str_vars.add(tgt.id)

        if not has_return_value:
            ret_type = void
        else:
            # Float-typed params (from call-site analysis or sig override).
            # Treat these as float for local-type-propagation purposes — a
            # return expression that mentions such a param should yield float.
            float_params = set()
            for i, pname in enumerate(param_names):
                if i < len(call_types) and call_types[i] == "float":
                    float_params.add(pname)
            float_vars = set(float_params)
            list_vars = set()
            dict_vars = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if isinstance(tgt, ast.Name):
                            if isinstance(n.value, (ast.List, ast.ListComp, ast.Set, ast.SetComp)):
                                list_vars.add(tgt.id)
                            elif isinstance(n.value, (ast.Dict, ast.DictComp)):
                                list_vars.add(tgt.id)
                                dict_vars.add(tgt.id)
                            elif isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                                str_vars.add(tgt.id)
                            elif isinstance(n.value, ast.JoinedStr):
                                str_vars.add(tgt.id)
                            elif (isinstance(n.value, ast.Call)
                                  and isinstance(n.value.func, ast.Name)
                                  and n.value.func.id in self._user_classes):
                                # `x = ClassName(...)` — x holds an obj
                                obj_vars.add(tgt.id)
                            elif (isinstance(n.value, ast.Name)
                                  and n.value.id in obj_vars):
                                # `x = y` where y is known obj
                                obj_vars.add(tgt.id)
                            elif isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Add):
                                # result = result + ch (string concat pattern)
                                if isinstance(n.value.left, ast.Name) and n.value.left.id in str_vars:
                                    str_vars.add(tgt.id)
                            else:
                                for sub in ast.walk(n.value):
                                    if isinstance(sub, ast.Constant) and isinstance(sub.value, float):
                                        float_vars.add(tgt.id)
                                        break
                                    # BinOp involving a float param → float var
                                    if (isinstance(sub, ast.Name)
                                            and sub.id in float_params):
                                        float_vars.add(tgt.id)
                                        break

            # Check return expression type (skip nested function returns)
            for n in ast.walk(node):
                if id(n) in _nested_ids:
                    continue
                if isinstance(n, ast.Return) and n.value is not None:
                    if isinstance(n.value, ast.Tuple):
                        ret_type = i8_ptr
                        break
                    # Direct list/dict literal or comp returns
                    if isinstance(n.value, (ast.List, ast.ListComp, ast.Dict,
                                             ast.DictComp, ast.Set, ast.SetComp)):
                        ret_type = i8_ptr
                        break
                    # Direct string-literal return
                    if (isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str)):
                        ret_type = i8_ptr
                        break
                    # Check if returning a list/dict/string/obj variable
                    if isinstance(n.value, ast.Name) and n.value.id in list_vars:
                        ret_type = i8_ptr
                        break
                    if isinstance(n.value, ast.Name) and n.value.id in str_vars:
                        ret_type = i8_ptr
                        break
                    if isinstance(n.value, ast.Name) and n.value.id in obj_vars:
                        ret_type = i8_ptr
                        break
                    # Check if returning a JoinedStr (f-string)
                    if isinstance(n.value, ast.JoinedStr):
                        ret_type = i8_ptr
                        break
                    # Returning a string-returning method call like s.upper(),
                    # s.strip(), s.replace(...) etc.
                    if (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Attribute)
                            and n.value.func.attr in (
                                "upper", "lower", "strip", "lstrip", "rstrip",
                                "replace", "capitalize", "title", "swapcase",
                                "center", "ljust", "rjust", "zfill", "join",
                                "format")):
                        ret_type = i8_ptr
                        break
                    # Returning a list-returning method call like d.keys(),
                    # d.values(), d.items(), s.split(), etc.
                    if (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Attribute)
                            and n.value.func.attr in (
                                "keys", "values", "items", "split",
                                "splitlines")):
                        ret_type = i8_ptr
                        break
                    # Returning a builtin that produces a string
                    if (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name)
                            and n.value.func.id in ("str", "repr", "hex",
                                                     "bin", "oct", "chr")):
                        ret_type = i8_ptr
                        break
                    # Returning a builtin that produces a list
                    if (isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name)
                            and n.value.func.id in (
                                "sorted", "reversed", "list", "range",
                                "map", "filter", "zip", "enumerate", "tuple")):
                        ret_type = i8_ptr
                        break
                    # Slice of a list-typed param → list
                    if (isinstance(n.value, ast.Subscript)
                            and isinstance(n.value.slice, ast.Slice)
                            and isinstance(n.value.value, ast.Name)
                            and n.value.value.id in param_names):
                        pidx = param_names.index(n.value.value.id)
                        if (pidx < len(call_types)
                                and call_types[pidx] is not None
                                and call_types[pidx].startswith("list")):
                            ret_type = i8_ptr
                            break
                    # str + str, str * int, etc. → str return
                    if (isinstance(n.value, ast.BinOp)
                            and isinstance(n.value.op, (ast.Add, ast.Mult))):
                        op_operands = (n.value.left, n.value.right)
                        found_str = False
                        for operand in op_operands:
                            if (isinstance(operand, ast.Name)
                                    and operand.id in param_names):
                                pidx = param_names.index(operand.id)
                                if (pidx < len(call_types)
                                        and call_types[pidx] == "str"):
                                    found_str = True
                                    break
                            if (isinstance(operand, ast.Constant)
                                    and isinstance(operand.value, str)):
                                found_str = True
                                break
                        if found_str:
                            ret_type = i8_ptr
                            break
                    # Returning a subscript on a param typed as a pointer-
                    # element container (list:str / list:list / list:dict /
                    # dict:list / dict:dict / dict:str) → pointer return.
                    # Also: slice of a str param → str.
                    if (isinstance(n.value, ast.Subscript)
                            and isinstance(n.value.value, ast.Name)
                            and n.value.value.id in param_names):
                        pidx = param_names.index(n.value.value.id)
                        if pidx < len(call_types) and call_types[pidx] is not None:
                            ct = call_types[pidx]
                            if ct in ("list:str", "dict:str",
                                      "list:list", "list:dict",
                                      "dict:list", "dict:dict"):
                                ret_type = i8_ptr
                                break
                            if (ct == "str"
                                    and isinstance(n.value.slice, ast.Slice)):
                                ret_type = i8_ptr
                                break
                    # Returning a param that is a pointer-typed container
                    # (list/dict/str) → pointer return.
                    if (isinstance(n.value, ast.Name)
                            and n.value.id in param_names):
                        pidx = param_names.index(n.value.id)
                        if pidx < len(call_types) and call_types[pidx] is not None:
                            ct = call_types[pidx]
                            if (ct == "str" or ct == "dict"
                                    or ct.startswith("list")
                                    or ct.startswith("dict:")):
                                ret_type = i8_ptr
                                break
                    # Check if returning a BinOp / IfExp / etc. containing strings.
                    # Skip strings that appear only as subscript keys (e.g.
                    # `d["k"]` where "k" is a key, not a string operand).
                    if isinstance(n.value, (ast.BinOp, ast.IfExp)):
                        has_str = False
                        # Collect subscript-key Constants to exclude
                        subscript_keys: set[int] = set()
                        for sub in ast.walk(n.value):
                            if (isinstance(sub, ast.Subscript)
                                    and isinstance(sub.slice, ast.Constant)):
                                subscript_keys.add(id(sub.slice))
                        # Subscripts on str-valued param containers count as
                        # string operands (e.g. d["a"] + d["b"] where d is
                        # dict:str or list:str).
                        for sub in ast.walk(n.value):
                            if (isinstance(sub, ast.Subscript)
                                    and isinstance(sub.value, ast.Name)
                                    and sub.value.id in param_names):
                                pidx = param_names.index(sub.value.id)
                                if (pidx < len(call_types)
                                        and call_types[pidx] in ("dict:str", "list:str")):
                                    has_str = True
                                    break
                        if has_str:
                            ret_type = i8_ptr
                            break
                        for sub in ast.walk(n.value):
                            if (isinstance(sub, ast.Constant)
                                    and isinstance(sub.value, str)
                                    and id(sub) not in subscript_keys):
                                has_str = True
                                break
                            if isinstance(sub, ast.JoinedStr):
                                has_str = True
                                break
                            if isinstance(sub, ast.Name) and sub.id in str_vars:
                                has_str = True
                                break
                        if has_str:
                            ret_type = i8_ptr
                            break
                    # Check if returning a float variable
                    if isinstance(n.value, ast.Name) and n.value.id in float_vars:
                        ret_type = double
                        break
                    # Check for Div operator (always returns float)
                    for sub in ast.walk(n.value):
                        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
                            ret_type = double
                            break
                    if ret_type == double:
                        break
                    # Check for float constants in return expression, or
                    # references to float-typed params (monomorphization).
                    returns_float = False
                    for sub in ast.walk(n.value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, float):
                            returns_float = True
                            break
                        if (isinstance(sub, ast.Name)
                                and sub.id in float_params):
                            returns_float = True
                            break
                    if returns_float:
                        ret_type = double
                        break
                    # Bool-returning: direct Compare, UnaryOp Not, bool
                    # Constant, or BoolOp with all-bool-ish operands
                    if isinstance(n.value, ast.Compare):
                        ret_type = i32
                        break
                    if (isinstance(n.value, ast.UnaryOp)
                            and isinstance(n.value.op, ast.Not)):
                        ret_type = i32
                        break
                    if (isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, bool)):
                        ret_type = i32
                        break
                    if isinstance(n.value, ast.BoolOp) and all(
                            isinstance(v, ast.Compare)
                            or (isinstance(v, ast.UnaryOp)
                                and isinstance(v.op, ast.Not))
                            or (isinstance(v, ast.Constant)
                                and isinstance(v.value, bool))
                            for v in n.value.values):
                        ret_type = i32
                        break

        # Detect generator functions (contain yield/yield from)
        is_generator = any(
            isinstance(n, (ast.Yield, ast.YieldFrom))
            for n in ast.walk(node)
        )
        # Generators using yield-as-expression (x=yield) need CPython's
        # coroutine support. Skip the LLVM declaration entirely — the
        # function will be compiled through CPython bridge and stored as
        # a pyobj variable in fastpy_main.
        if is_generator and self._generator_needs_cpython(node):
            effective_name = _name_override if _name_override else node.name
            if not hasattr(self, '_cpython_generators'):
                self._cpython_generators = set()
            self._cpython_generators.add(effective_name)
            return
        if is_generator:
            self._generator_funcs.add(
                _name_override if _name_override else node.name)
            # Generators return a list (of yielded values)
            ret_type = i8_ptr
            ret_tag = "ptr:list"

        # Remember the statically-inferred bare types — the body expects
        # these, and we'll unwrap FpyValue params at entry to match.
        static_param_types = list(param_types)
        static_ret_type = ret_type

        # Post-refactor ABI: regular user functions take FpyValue params
        # and return FpyValue. Vararg/kwarg functions keep their special
        # signatures (they pack args into a list/dict themselves).
        uses_fv = not (has_vararg or has_kwarg)
        if uses_fv:
            fv_ret = fpy_val if ret_type != void else void
            func_type = ir.FunctionType(fv_ret, [fpy_val] * len(param_names))
        else:
            func_type = ir.FunctionType(ret_type, param_types)

        # When specializing, use the mangled name for the LLVM symbol too,
        # so the specializations don't collide at link time.
        effective_name = _name_override if _name_override else node.name
        fn_name = f"fastpy.user.{effective_name}"
        func = ir.Function(self.module, func_type, name=fn_name)

        # Inline hint: tell LLVM to prefer inlining user functions.
        # LLVM's -O2 inliner already handles most cases, but the hint
        # helps with FpyValue wrap/unwrap elimination via SROA when
        # functions are small enough to inline.
        func.attributes.add('inlinehint')

        for param, name in zip(func.args, param_names):
            param.name = name

        # Determine semantic return tag (may differ from LLVM type)
        returns_str = False
        returns_dict = False
        returns_list = False
        for n in ast.walk(node):
            if isinstance(n, ast.Return) and n.value is not None:
                if isinstance(n.value, ast.JoinedStr):
                    returns_str = True
                elif isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    returns_str = True
                elif isinstance(n.value, ast.Name) and n.value.id in str_vars:
                    returns_str = True
                elif isinstance(n.value, (ast.Dict, ast.DictComp)):
                    returns_dict = True
                elif isinstance(n.value, (ast.List, ast.ListComp, ast.Tuple)):
                    returns_list = True
                elif (isinstance(n.value, ast.Name)
                        and has_return_value
                        and n.value.id in dict_vars):
                    returns_dict = True
                elif (isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Attribute)
                        and n.value.func.attr in (
                            "upper", "lower", "strip", "lstrip", "rstrip",
                            "replace", "capitalize", "title", "swapcase",
                            "center", "ljust", "rjust", "zfill", "join",
                            "format")):
                    returns_str = True
                elif (isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Attribute)
                        and n.value.func.attr in ("keys", "values", "items",
                                                   "split", "splitlines")):
                    returns_list = True
                elif (isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Name)
                        and n.value.func.id in ("str", "repr", "hex",
                                                 "bin", "oct", "chr")):
                    returns_str = True
                elif (isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Name)
                        and n.value.func.id in ("sorted", "reversed", "list",
                                                 "range", "map", "filter",
                                                 "zip", "enumerate", "tuple")):
                    returns_list = True
                elif isinstance(n.value, (ast.BinOp, ast.IfExp)):
                    # Check if any operand is a string constant/joinedstr/str var
                    for sub in ast.walk(n.value):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            returns_str = True
                            break
                        if isinstance(sub, ast.JoinedStr):
                            returns_str = True
                            break
                        if isinstance(sub, ast.Name) and sub.id in str_vars:
                            returns_str = True
                            break
                        # Str-typed param
                        if isinstance(sub, ast.Name) and sub.id in param_names:
                            pidx = param_names.index(sub.id)
                            if (pidx < len(call_types)
                                    and call_types[pidx] == "str"):
                                returns_str = True
                                break
                        # Subscript on a str-valued param container
                        if (isinstance(sub, ast.Subscript)
                                and isinstance(sub.value, ast.Name)
                                and sub.value.id in param_names):
                            pidx = param_names.index(sub.value.id)
                            if (pidx < len(call_types)
                                    and call_types[pidx] in ("dict:str", "list:str")):
                                returns_str = True
                                break
                elif (isinstance(n.value, ast.Subscript)
                        and isinstance(n.value.value, ast.Name)
                        and n.value.value.id in param_names):
                    # Subscript on a param whose element type is known
                    pidx = param_names.index(n.value.value.id)
                    if pidx < len(call_types) and call_types[pidx] is not None:
                        ct = call_types[pidx]
                        if ct in ("list:str", "dict:str"):
                            returns_str = True
                        elif ct in ("list:dict", "dict:dict"):
                            returns_dict = True
                        elif ct in ("list:list", "dict:list"):
                            returns_list = True
                        elif (ct == "str"
                                and isinstance(n.value.slice, ast.Slice)):
                            returns_str = True
                elif (isinstance(n.value, ast.Name)
                        and n.value.id in param_names):
                    # Param pass-through: inherit type info from call site
                    pidx = param_names.index(n.value.id)
                    if pidx < len(call_types) and call_types[pidx] is not None:
                        ct = call_types[pidx]
                        if ct == "str":
                            returns_str = True
                        elif ct == "dict" or ct.startswith("dict:"):
                            returns_dict = True
                        elif ct.startswith("list"):
                            returns_list = True

        # Detect obj-valued returns (variable tracked in obj_vars from the
        # local type-tracking scan above) so ret_tag is "obj" rather than
        # "ptr"/"str" which downstream treats as list or string.
        returns_obj = False
        for n in ast.walk(node):
            if isinstance(n, ast.Return) and n.value is not None:
                if (isinstance(n.value, ast.Name)
                        and n.value.id in obj_vars):
                    returns_obj = True
                    break
                if (isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Name)
                        and n.value.func.id in self._user_classes):
                    returns_obj = True
                    break

        if ret_type == i64:
            ret_tag = "str" if returns_str else "int"
        elif ret_type == double:
            ret_tag = "float"
        elif ret_type == i32:
            ret_tag = "bool"
        elif ret_type == i8_ptr:
            if (has_kwarg and returns_param) or returns_dict:
                ret_tag = "dict"
            elif returns_str:
                ret_tag = "str"
            elif returns_obj:
                ret_tag = "obj"
            else:
                ret_tag = "ptr"  # list/tuple
                # Try to determine list element type from return statements
                for n in ast.walk(node):
                    if isinstance(n, ast.Return) and n.value is not None and isinstance(n.value, ast.Name):
                        ret_var = n.value.id
                        # Check if this variable is built by appending lists
                        for stmt in node.body:
                            for s in ast.walk(stmt):
                                if (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                                        and isinstance(s.value.func, ast.Attribute)
                                        and s.value.func.attr == "append"
                                        and isinstance(s.value.func.value, ast.Name)
                                        and s.value.func.value.id == ret_var
                                        and len(s.value.args) == 1):
                                    arg = s.value.args[0]
                                    if isinstance(arg, (ast.List, ast.ListComp)):
                                        ret_tag = "ptr:list"
                                        break
                                    elif isinstance(arg, ast.Name):
                                        # Check if the appended variable is assigned a list
                                        for s2 in ast.walk(node):
                                            if (isinstance(s2, ast.Assign) and len(s2.targets) == 1
                                                    and isinstance(s2.targets[0], ast.Name)
                                                    and s2.targets[0].id == arg.id
                                                    and isinstance(s2.value, (ast.List, ast.ListComp))):
                                                ret_tag = "ptr:list"
                                                break
                                    if ret_tag == "ptr:list":
                                        break
                            if ret_tag == "ptr:list":
                                break
                    if ret_tag == "ptr:list":
                        break
        else:
            ret_tag = "void"
        # For functions with keyword-only args, combine their defaults into
        # one right-aligned list matching the combined param_names.
        # kw_defaults has one entry per kwonlyarg (None if no default).
        defaults = list(node.args.defaults)
        if hasattr(node.args, 'kwonlyargs') and node.args.kwonlyargs:
            # Fill in None placeholders for kwonlyargs without defaults,
            # then keep the defaults that are actually provided.
            # Track separately via min_args accounting below.
            for kwd in node.args.kw_defaults:
                if kwd is not None:
                    defaults.append(kwd)
                # kwonly without default: must be provided via keyword,
                # otherwise call will fail. We don't append a placeholder
                # since defaults is right-aligned.
        # Detect whether any return path yields None (explicit `return None`,
        # bare `return`, implicit fallthrough, or `return param` where param
        # has a None default). Used by the call site to decide whether to
        # preserve the raw FpyValue (NONE tag).
        _may_return_none = False
        has_value_return = False
        # Collect params with None defaults
        none_default_params: set[str] = set()
        n_params = len(param_names)
        for di, d in enumerate(node.args.defaults):
            if isinstance(d, ast.Constant) and d.value is None:
                pidx = n_params - len(node.args.defaults) + di
                if pidx < n_params:
                    none_default_params.add(param_names[pidx])
        for n in ast.walk(node):
            if isinstance(n, ast.Return):
                if n.value is None:
                    _may_return_none = True
                elif (isinstance(n.value, ast.Constant)
                        and n.value.value is None):
                    _may_return_none = True
                elif (isinstance(n.value, ast.Name)
                        and n.value.id in none_default_params):
                    # `return default` where default=None
                    _may_return_none = True
                else:
                    has_value_return = True
        # Implicit None: if the function has `return <value>` somewhere but
        # the body can fall through without hitting a return (e.g., the
        # body ends with an `if` without `else`), it implicitly returns
        # None on the fallthrough path.
        if has_value_return and not _may_return_none:
            last_stmt = node.body[-1] if node.body else None
            if not isinstance(last_stmt, ast.Return):
                _may_return_none = True
        self._user_functions[effective_name] = FuncInfo(
            func=func,
            ret_tag=ret_tag,
            param_count=len(param_names),
            defaults=defaults,
            min_args=len(param_names) - len(defaults),
            is_vararg=has_vararg,
            is_kwarg=has_kwarg,
            static_param_types=static_param_types,
            static_ret_type=static_ret_type,
            uses_fv_abi=uses_fv,
            may_return_none=_may_return_none,
        )
        # Track the function's AST so callers can inspect what it returns
        # (used to propagate dict-value-type flags to assignment targets).
        if not hasattr(self, "_function_def_nodes"):
            self._function_def_nodes = {}
        self._function_def_nodes[effective_name] = node
        # For specializations, also index under the un-mangled name so any
        # lookup that predates specialization resolution still finds a node.
        if _name_override is not None:
            self._function_def_nodes.setdefault(node.name, node)

    def _find_returned_dict_literal(self, fn_def: ast.FunctionDef) -> ast.Dict | None:
        """If the function unconditionally returns a dict literal, return it.
        Returns None if multiple return paths or the return isn't a literal.
        """
        result = None
        for n in ast.walk(fn_def):
            if isinstance(n, ast.Return) and n.value is not None:
                if isinstance(n.value, ast.Dict):
                    if result is not None and result is not n.value:
                        return None  # multiple return literals — not safe
                    result = n.value
                else:
                    return None  # at least one non-literal return
        return result

    def _detect_string_params(self, node: ast.FunctionDef) -> set[str]:
        """Detect function parameters likely used as strings."""
        param_names = [arg.arg for arg in node.args.args]
        kw_names = [arg.arg for arg in node.args.kwonlyargs]
        string_params = set()

        # Check for string default values (positional defaults are right-aligned)
        defaults = node.args.defaults
        n_defaults = len(defaults)
        n_params = len(param_names)
        for i, default in enumerate(defaults):
            param_idx = n_params - n_defaults + i
            if isinstance(default, ast.Constant) and isinstance(default.value, str):
                string_params.add(param_names[param_idx])

        # Keyword-only defaults align 1:1 with kwonlyargs (None = no default)
        for name, default in zip(kw_names, node.args.kw_defaults):
            if (default is not None
                    and isinstance(default, ast.Constant)
                    and isinstance(default.value, str)):
                string_params.add(name)

        for n in ast.walk(node):
            # Param used in f-string: f"...{param}..."
            if isinstance(n, ast.FormattedValue):
                if isinstance(n.value, ast.Name) and n.value.id in set(param_names):
                    string_params.add(n.value.id)
                # Also check attribute access in f-strings: f"...{self.name}..."
                if isinstance(n.value, ast.Attribute) and isinstance(n.value.value, ast.Name):
                    attr_name = n.value.attr
                    # Check if any `self.attr = param` exists in this method
                    for assign in ast.walk(node):
                        if isinstance(assign, ast.Assign):
                            for tgt in assign.targets:
                                if (isinstance(tgt, ast.Attribute)
                                        and isinstance(tgt.value, ast.Name)
                                        and tgt.value.id == "self"
                                        and tgt.attr == attr_name):
                                    if isinstance(assign.value, ast.Name) and assign.value.id in set(param_names):
                                        string_params.add(assign.value.id)

        # Check class-level string attributes: if self.attr is a string attr
        # and self.attr = param exists, the param is a string
        class_str_attrs = getattr(self, '_class_string_attrs', set())
        if class_str_attrs:
            for n in ast.walk(node):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"
                                and tgt.attr in class_str_attrs):
                            if isinstance(n.value, ast.Name) and n.value.id in set(param_names):
                                string_params.add(n.value.id)
            # Param used in string concat: param + "..."
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                for side in (n.left, n.right):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        other = n.right if side is n.left else n.left
                        if isinstance(other, ast.Name) and other.id in set(param_names):
                            string_params.add(other.id)

        # Param used in subscript: param[i] — likely string indexing.
        # Also check param used in string method calls: param.upper(), etc.
        str_methods = {"upper", "lower", "strip", "lstrip", "rstrip", "split",
                       "join", "replace", "startswith", "endswith", "find",
                       "count", "index", "title", "capitalize", "isdigit",
                       "isalpha", "format"}
        for n in ast.walk(node):
            if isinstance(n, ast.Subscript):
                if (isinstance(n.value, ast.Name)
                        and n.value.id in set(param_names)):
                    # If the call-site says this param is a string, mark it
                    call_types = self._call_site_param_types.get(
                        node.name, [])
                    pidx = param_names.index(n.value.id)
                    if pidx < len(call_types) and call_types[pidx] == "str":
                        string_params.add(n.value.id)
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id in set(param_names)
                    and n.func.attr in str_methods):
                string_params.add(n.func.value.id)

        return string_params

    def _emit_function_def(self, node: ast.FunctionDef,
                           _sig_override: list | None = None,
                           _name_override: str | None = None) -> None:
        """Generate code for a user function body.

        When the function was monomorphized in _declare_user_function, emit
        one body per specialization by recursing with the specialization's
        signature and mangled name.
        """
        # Dispatch to specializations on the top-level call
        if _sig_override is None and _name_override is None:
            specs = self._monomorphized.get(node.name)
            if specs:
                for sig in specs:
                    mangled = f"{node.name}__{self._mangle_sig(sig)}"
                    self._emit_function_def(
                        node, _sig_override=list(sig),
                        _name_override=mangled)
                return

        effective_name = _name_override if _name_override else node.name

        # CPython generators: skip body emission. The function will be
        # compiled and stored via CPython bridge in fastpy_main.
        if effective_name in getattr(self, '_cpython_generators', set()):
            return

        info = self._user_functions[effective_name]

        # Save outer state. Dict-value-type sets are scoped per-function so
        # a `d` param in one function doesn't pollute another's heuristics.
        saved = (self.function, self.builder, self.variables, self._loop_stack,
                 self._list_append_types,
                 self._dict_var_int_values, self._dict_var_list_values,
                 self._dict_var_dict_values, self._dict_var_obj_values,
                 self._dict_var_key_types,
                 self._obj_var_class)

        # Set up function state
        self.function = info.func
        entry = info.func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self._loop_stack = []
        self._list_append_types = {}
        self._dict_var_int_values = set()
        self._dict_var_list_values = set()
        self._dict_var_dict_values = set()
        self._dict_var_obj_values = set()
        self._dict_var_key_types = {}
        self._obj_var_class = {}

        # Pre-scan function body for list append patterns. Build a
        # param-name → type map from call-site analysis so `for c in s:`
        # where `s` is a str-typed param can feed str-typed append() calls.
        prescan_known: dict[str, str] = {}
        pre_param_names = [a.arg for a in node.args.args]
        pre_param_names += [a.arg for a in node.args.kwonlyargs]
        pre_call_types = self._call_site_param_types.get(node.name, [])
        for i, pname in enumerate(pre_param_names):
            if i < len(pre_call_types) and pre_call_types[i] is not None:
                prescan_known[pname] = pre_call_types[i]
        self._prescan_list_append_types(node.body, prescan_known)
        self._current_scope_stmts = node.body

        # Detect which params are used as strings (in f-strings, concat, etc.)
        string_params = self._detect_string_params(node)

        # Detect params with bool defaults (e.g. def f(x, verbose=False))
        bool_default_params: set[str] = set()
        pos_params = [a.arg for a in node.args.args]
        for di, d in enumerate(node.args.defaults):
            pidx = len(pos_params) - len(node.args.defaults) + di
            if (isinstance(d, ast.Constant)
                    and isinstance(d.value, bool)
                    and 0 <= pidx < len(pos_params)):
                bool_default_params.add(pos_params[pidx])
        # And kwonly bool defaults
        for name, d in zip([a.arg for a in node.args.kwonlyargs],
                            node.args.kw_defaults):
            if (d is not None and isinstance(d, ast.Constant)
                    and isinstance(d.value, bool)):
                bool_default_params.add(name)

        # Store parameters as local variables
        has_vararg = node.args.vararg is not None
        has_kwarg = node.args.kwarg is not None
        if _sig_override is not None:
            # Specialization: use the signature directly so each body sees
            # its own concrete param types instead of the merged "mixed".
            call_types = list(_sig_override)
            pos_and_kw = [a.arg for a in node.args.args]
            pos_and_kw += [a.arg for a in node.args.kwonlyargs]
            while len(call_types) < len(pos_and_kw):
                call_types.append(None)
        else:
            call_types = self._call_site_param_types.get(node.name, [])

        for param_idx, param in enumerate(info.func.args):
            if info.uses_fv_abi:
                # Param is an FpyValue struct. With _USE_FV_LOCALS, we store
                # it directly into an fpy_val alloca — _load_variable will
                # unwrap based on the variable's tag. Determine the static
                # tag so the symbol table knows the expected bare type on load.
                static_type = info.static_param_types[param_idx]
                if isinstance(static_type, ir.PointerType):
                    call_tag = (call_types[param_idx]
                                if param_idx < len(call_types) else None)
                    if call_tag is not None and call_tag.startswith("list"):
                        tag = call_tag if ":" in call_tag else "list:int"
                    elif call_tag is not None and call_tag.startswith("dict"):
                        # Strip the value-type suffix from the variable tag
                        # (downstream expects bare "dict") but record the
                        # value-type in the matching helper set so d[k] can
                        # unwrap to the right bare LLVM type.
                        tag = "dict"
                        if call_tag == "dict:int":
                            self._dict_var_int_values.add(param.name)
                        elif call_tag == "dict:list":
                            self._dict_var_list_values.add(param.name)
                        elif call_tag == "dict:dict":
                            self._dict_var_dict_values.add(param.name)
                    elif call_tag == "obj":
                        tag = "obj"
                    else:
                        tag = "str"
                elif isinstance(static_type, ir.DoubleType):
                    tag = "float"
                elif param.name in bool_default_params:
                    tag = "bool"
                else:
                    tag = "int"

                if self._USE_FV_LOCALS:
                    # Store FpyValue directly — _load_variable unwraps on demand
                    alloca = self.builder.alloca(fpy_val, name=param.name)
                    self.builder.store(param, alloca)
                    self.variables[param.name] = (alloca, tag)
                    # Record the specific class for obj-typed params so
                    # downstream attr accesses can resolve through
                    # _obj_var_class → _class_obj_attr_types.
                    if tag == "obj":
                        param_cls_map = getattr(
                            self, '_csa_func_param_classes', {}).get(
                            node.name, {})
                        if param_idx in param_cls_map:
                            self._obj_var_class[param.name] = param_cls_map[param_idx]
                    continue

                # Legacy: unpack to bare type
                if isinstance(static_type, ir.IntType) and static_type.width == 64:
                    bare = self._fv_as_int(param)
                elif isinstance(static_type, ir.DoubleType):
                    bare = self._fv_as_float(param)
                elif isinstance(static_type, ir.PointerType):
                    bare = self._fv_as_ptr(param)
                else:
                    bare = self._fv_data_i64(param)
                alloca = self.builder.alloca(bare.type, name=param.name)
                self.builder.store(bare, alloca)
                self.variables[param.name] = (alloca, tag)
                continue

            # Old ABI path (vararg/kwarg only)
            alloca = self.builder.alloca(param.type, name=param.name)
            self.builder.store(param, alloca)
            if isinstance(param.type, ir.PointerType):
                if has_vararg and not has_kwarg:
                    tag = "list:int"
                elif has_kwarg:
                    tag = "dict"
                else:
                    tag = "str"
            elif isinstance(param.type, ir.DoubleType):
                tag = "float"
            elif param.name in string_params and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                alloca = self.builder.alloca(i8_ptr, name=param.name)
                self.builder.store(ptr_val, alloca)
                tag = "str"
            else:
                tag = "int"
            self.variables[param.name] = (alloca, tag)

        # Generator setup: create a list to collect yielded values
        is_gen = effective_name in self._generator_funcs
        if is_gen:
            gen_list = self.builder.call(self.runtime["list_new"], [])
            self._gen_list = gen_list  # store for yield emission

        # Emit function body
        self._emit_stmts(node.body)

        # Add implicit return if needed
        if not self.builder.block.is_terminated:
            if is_gen:
                # Generator: return the collected list
                ret_ty = info.func.return_value.type
                if isinstance(ret_ty, ir.LiteralStructType):
                    self.builder.ret(self._fv_from_list(gen_list))
                else:
                    self.builder.ret(gen_list)
            else:
                ret_ty = info.func.return_value.type
                if isinstance(ret_ty, ir.VoidType):
                    self.builder.ret_void()
                elif isinstance(ret_ty, ir.LiteralStructType):
                    # FpyValue return: implicit return is None
                    self.builder.ret(self._fv_none())
                else:
                    self.builder.ret(ir.Constant(ret_ty, 0))

        if is_gen:
            self._gen_list = None

        # Restore outer state
        (self.function, self.builder, self.variables, self._loop_stack,
         self._list_append_types,
         self._dict_var_int_values, self._dict_var_list_values,
         self._dict_var_dict_values, self._dict_var_obj_values,
         self._dict_var_key_types,
         self._obj_var_class) = saved

    # -----------------------------------------------------------------
    # Class support
    # -----------------------------------------------------------------

    def _class_var_is_mutated(self, class_node: ast.ClassDef,
                                attr_name: str) -> bool:
        """Check if `ClassName.attr` is ever assigned in the program,
        other than its initial class-level definition.
        """
        cls_name = class_node.name
        tree = getattr(self, "_csa_root_tree", None)
        if tree is None:
            return False
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Assign) and len(n.targets) == 1):
                continue
            tgt = n.targets[0]
            if (isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == cls_name
                    and tgt.attr == attr_name):
                return True
            # AugAssign-like pattern after walking; we accept plain Assign only
        return False

    def _declare_class(self, node: ast.ClassDef,
                       _sig_override: list | None = None,
                       _name_override: str | None = None) -> None:
        """Forward-declare a class and all its methods.

        When _sig_override and _name_override are provided, declare a
        monomorphized variant under the overridden name. When they are
        None and the class has scalar-conflicting constructor sigs,
        declare one variant per signature and register them in
        self._monomorphized_classes, then also keep the original name as
        an alias pointing to the first variant's ClassInfo.
        """
        # Top-level entry: check for monomorphization
        if _sig_override is None and _name_override is None:
            if node.name in self._user_classes:
                return
            sigs = self._function_signatures.get(node.name, [])
            # Monomorphize classes whose constructor has scalar-conflicting
            # sigs (e.g. Processor(int) and Processor(float)).
            if self._signature_scalar_conflict(sigs):
                self._monomorphized_classes[node.name] = list(sigs)
                # Propagate call-types per variant so methods see the right
                # attr types. We override _call_site_param_types under the
                # mangled name.
                for sig in sigs:
                    mangled = f"{node.name}__{self._mangle_sig(sig)}"
                    # Prefix the sig with None for the 'self' position
                    # (class call-site types start at arg 0 = first init param
                    # after self; _detect_class_float_attrs already skips
                    # self). _call_site_param_types for the class uses the
                    # same convention as the original name.
                    self._call_site_param_types[mangled] = list(sig)
                    # Propagate method sigs under the variant name too.
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            key = f"{node.name}.{item.name}"
                            var_key = f"{mangled}.{item.name}"
                            if key in self._call_site_param_types:
                                self._call_site_param_types[var_key] = list(
                                    self._call_site_param_types[key])
                    self._declare_class(node, _sig_override=list(sig),
                                         _name_override=mangled)
                # Register the first variant as alias under the original name
                if sigs:
                    first_mangled = f"{node.name}__{self._mangle_sig(sigs[0])}"
                    if first_mangled in self._user_classes:
                        self._user_classes[node.name] = self._user_classes[first_mangled]
                return
        else:
            if _name_override and _name_override in self._user_classes:
                return

        class_name = _name_override if _name_override else node.name
        parent_name = None
        # Collect ALL base class names for multiple inheritance.
        # parent_name is the primary (first) base used for the runtime
        # parent_id chain. secondary_bases hold additional bases whose
        # methods are flattened into the child class directly.
        secondary_bases: list[str] = []

        # Extract metaclass= keyword argument (for metaclass support)
        metaclass_name = None
        for kw in node.keywords:
            if kw.arg == "metaclass" and isinstance(kw.value, ast.Name):
                metaclass_name = kw.value.id
        if metaclass_name:
            if not hasattr(self, '_class_metaclasses'):
                self._class_metaclasses = {}
            self._class_metaclasses[class_name] = metaclass_name

        if node.bases:
            if isinstance(node.bases[0], ast.Name):
                parent_name = node.bases[0].id
                # `type` as a base class — metaclass definition (class M(type))
                # Treat as having no runtime parent since `type` is not a
                # user class. The class itself is registered normally.
                if parent_name == "type":
                    parent_name = None
                # Resolve parent variant if parent is monomorphized. For
                # simple cases, inherit from the first variant.
                if parent_name in self._monomorphized_classes:
                    parent_sigs = self._monomorphized_classes[parent_name]
                    if parent_sigs:
                        parent_name = f"{parent_name}__{self._mangle_sig(parent_sigs[0])}"
            for base_node in node.bases[1:]:
                if isinstance(base_node, ast.Name):
                    bname = base_node.id
                    if bname in self._monomorphized_classes:
                        bsigs = self._monomorphized_classes[bname]
                        if bsigs:
                            bname = f"{bname}__{self._mangle_sig(bsigs[0])}"
                    secondary_bases.append(bname)

        # Pre-scan __init__ for list/dict attribute assignments
        list_attrs, dict_attrs = self._detect_class_container_attrs(node, class_name)
        # Inherit from parent
        if parent_name and parent_name in self._class_container_attrs:
            p_list, p_dict = self._class_container_attrs[parent_name]
            list_attrs |= p_list
            dict_attrs |= p_dict
        self._class_container_attrs[class_name] = (list_attrs, dict_attrs)

        # Pre-scan class body for class-level constant assignments (not inside methods)
        const_attrs: dict[str, ast.expr] = {}
        for item in node.body:
            if (isinstance(item, ast.Assign) and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)):
                const_attrs[item.targets[0].id] = item.value
        self._class_const_attrs[class_name] = const_attrs

        # For class-level constants with mutable-looking usage (i.e.,
        # `ClassName.attr = ...` somewhere in the program), create LLVM
        # globals so reads/writes go through shared storage. Supports
        # int/float/bool/str/None constants.
        if not hasattr(self, "_class_var_globals"):
            self._class_var_globals = {}
        for attr_name, val_node in const_attrs.items():
            if not self._class_var_is_mutated(node, attr_name):
                continue
            if isinstance(val_node, ast.Constant):
                v = val_node.value
                if isinstance(v, bool):
                    gtype = i32
                    init = ir.Constant(i32, 1 if v else 0)
                elif isinstance(v, int):
                    gtype = i64
                    init = ir.Constant(i64, v)
                elif isinstance(v, float):
                    gtype = double
                    init = ir.Constant(double, v)
                elif isinstance(v, str):
                    # String globals — pointer to the string constant
                    str_ptr = self._make_string_constant(v)
                    gtype = i8_ptr
                    init = None  # will be set via initializer
                    gvar = ir.GlobalVariable(
                        self.module, gtype,
                        name=f"fastpy.classvar.{class_name}.{attr_name}")
                    # For string globals, the initializer is the bitcast pointer.
                    # llvmlite requires the initializer match the global's type.
                    gvar.linkage = "private"
                    gvar.initializer = ir.Constant(gtype, None)
                    # Store the string pointer in fastpy_main initialization.
                    if not hasattr(self, "_class_var_str_inits"):
                        self._class_var_str_inits = []
                    self._class_var_str_inits.append((gvar, v))
                    self._class_var_globals[(class_name, attr_name)] = (gvar, "str")
                    continue
                elif v is None:
                    gtype = i64
                    init = ir.Constant(i64, 0)
                else:
                    continue
                gvar = ir.GlobalVariable(
                    self.module, gtype,
                    name=f"fastpy.classvar.{class_name}.{attr_name}")
                gvar.linkage = "private"
                gvar.initializer = init
                tag = ("bool" if gtype == i32
                       else "float" if gtype == double
                       else ("none" if isinstance(val_node.value, type(None)) else "int"))
                self._class_var_globals[(class_name, attr_name)] = (gvar, tag)

        # Create a global variable to hold the runtime class_id
        class_id_global = ir.GlobalVariable(self.module, i32,
                                            name=f"fastpy.classid.{class_name}")
        class_id_global.initializer = ir.Constant(i32, -1)
        class_id_global.linkage = "private"

        methods: dict[str, ir.Function] = {}
        method_asts: dict = {}
        classmethods: set = set()
        staticmethods: set = set()
        properties: set = set()
        init_arg_count = 0
        init_defaults: list = []

        # Pre-compute element types for list attributes from call-site analysis.
        # This allows detecting that `return self.items[i]` returns a string
        # when `self.items.append(str_param)` is called.
        list_attr_elem_types: dict[str, str] = {}
        for method_node in node.body:
            if not isinstance(method_node, ast.FunctionDef):
                continue
            m_params = [arg.arg for arg in method_node.args.args]
            q_key = f"{class_name}.{method_node.name}"
            m_call_types = self._call_site_param_types.get(
                q_key, self._call_site_param_types.get(method_node.name, []))
            for n in ast.walk(method_node):
                if (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "append"
                        and isinstance(n.func.value, ast.Attribute)
                        and isinstance(n.func.value.value, ast.Name)
                        and n.func.value.value.id == "self"
                        and n.func.value.attr in list_attrs
                        and len(n.args) == 1):
                    attr_name = n.func.value.attr
                    arg = n.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        list_attr_elem_types[attr_name] = "str"
                    elif isinstance(arg, (ast.List, ast.ListComp)):
                        list_attr_elem_types[attr_name] = "list"
                    elif isinstance(arg, (ast.Dict, ast.DictComp)):
                        list_attr_elem_types[attr_name] = "dict"
                    elif isinstance(arg, ast.Name) and arg.id in m_params:
                        pidx = m_params.index(arg.id) - 1  # skip self
                        if 0 <= pidx < len(m_call_types) and m_call_types[pidx]:
                            ct = m_call_types[pidx]
                            if ct == "str":
                                list_attr_elem_types[attr_name] = "str"
                            elif ct.startswith("list"):
                                list_attr_elem_types[attr_name] = "list"
                            elif ct.startswith("dict"):
                                list_attr_elem_types[attr_name] = "dict"
                            elif ct == "obj":
                                list_attr_elem_types[attr_name] = "obj"

        # Pre-compute float, string, and bool attrs for return-type detection.
        # Uses _call_site_param_types (available from Pass 0.75). For
        # variants, use the variant's own call-types so attr typing matches
        # the constructor signature.
        float_attrs = self._detect_class_float_attrs(node, class_name)
        string_attrs = self._detect_class_string_attrs(node, class_name)
        bool_attrs = self._detect_class_bool_attrs(node, class_name)
        # Inherit from parent class
        if parent_name:
            float_attrs |= self._per_class_float_attrs.get(parent_name, set())
            string_attrs |= self._per_class_string_attrs.get(parent_name, set())
            bool_attrs |= self._per_class_bool_attrs.get(parent_name, set())
        # Store for child class inheritance during this pass
        self._per_class_float_attrs[class_name] = float_attrs
        self._per_class_string_attrs[class_name] = string_attrs
        self._per_class_bool_attrs[class_name] = bool_attrs

        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                dec_names = [d.id for d in item.decorator_list if isinstance(d, ast.Name)]
                method_name = item.name
                is_static = "staticmethod" in dec_names
                is_classmethod = "classmethod" in dec_names
                is_property = "property" in dec_names
                # @x.setter decorator: the method name matches a property
                is_setter = any(
                    isinstance(d, ast.Attribute) and d.attr == "setter"
                    for d in item.decorator_list)
                if is_classmethod:
                    classmethods.add(method_name)
                if is_static:
                    staticmethods.add(method_name)
                if is_property:
                    properties.add(method_name)
                if is_setter:
                    # @x.setter: compile as a separate function named x__set
                    # so it doesn't collide with the getter
                    method_name = f"{method_name}__set"
                params = [arg.arg for arg in item.args.args]

                if is_static:
                    param_types = [i64] * len(params)
                elif is_classmethod:
                    # classmethod: first param is `cls` (passed as class_id int)
                    param_types = [i32] + [i64] * (len(params) - 1)
                else:
                    # self is i8*, all other params are i64 (matching C dispatch ABI).
                    # For "mixed" params, add an extra i64 for the tag.
                    param_types = [i8_ptr]
                    mixed_param_indices: set[int] = set()
                    q_key = f"{class_name}.{method_name}"
                    m_cts = self._call_site_param_types.get(
                        q_key, self._call_site_param_types.get(method_name, []))
                    if not m_cts and method_name == "__init__":
                        m_cts = self._call_site_param_types.get(class_name, [])
                    for pi in range(1, len(params)):  # skip self
                        ci = pi - 1
                        if ci < len(m_cts) and m_cts[ci] == "mixed":
                            param_types.append(i64)  # tag
                            param_types.append(i64)  # data
                            mixed_param_indices.add(pi)
                        else:
                            param_types.append(i64)
                    if mixed_param_indices:
                        key = f"{class_name}.{method_name}"
                        if not hasattr(self, '_mixed_param_methods'):
                            self._mixed_param_methods = {}
                        self._mixed_param_methods[key] = mixed_param_indices

                    # Track which params need inttoptr in the body
                    obj_params = set()
                    for n in ast.walk(item):
                        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                            if n.value.id in params and n.value.id != "self":
                                obj_params.add(n.value.id)

                # Determine which params are floats (from call-site analysis)
                float_method_params: set[str] = set()
                q_key = f"{class_name}.{method_name}"
                m_call_types = self._call_site_param_types.get(
                    q_key, self._call_site_param_types.get(method_name, []))
                for pi, pname in enumerate(params[1:]):  # skip self
                    if pi < len(m_call_types) and m_call_types[pi] == "float":
                        float_method_params.add(pname)
                # Also check float defaults
                m_defaults = item.args.defaults
                for di, d in enumerate(m_defaults):
                    pidx = len(params) - len(m_defaults) + di
                    if isinstance(d, ast.Constant) and isinstance(d.value, float):
                        float_method_params.add(params[pidx])

                # Determine return type
                has_return = any(
                    isinstance(n, ast.Return) and n.value is not None
                    for n in ast.walk(item)
                )
                # __init__ and __str__ have special return handling
                if method_name == "__init__":
                    ret_type = void
                    init_arg_count = len(params) - 1  # exclude self
                    init_defaults = list(item.args.defaults)
                elif method_name in ("__str__", "__repr__"):
                    ret_type = i8_ptr  # returns string
                    param_types = [i8_ptr]  # just self
                else:
                    ret_type = i64 if has_return else void

                # Check for string or float returns
                if has_return and method_name not in ("__str__", "__repr__"):
                    for n in ast.walk(item):
                        if isinstance(n, ast.Return) and n.value is not None:
                            # Check for string return
                            if isinstance(n.value, (ast.Constant,)) and isinstance(getattr(n.value, 'value', None), str):
                                ret_type = i8_ptr
                                break
                            if isinstance(n.value, (ast.JoinedStr,)):
                                ret_type = i8_ptr
                                break
                            # Check for list / tuple / dict return
                            if isinstance(n.value, (ast.List, ast.ListComp, ast.Tuple,
                                                     ast.Dict, ast.DictComp)):
                                ret_type = i8_ptr
                                break
                            # Check for `return self` (fluent chain) — returns obj
                            if isinstance(n.value, ast.Name) and n.value.id == "self":
                                ret_type = i8_ptr
                                break
                            # return local_var where local was assigned from
                            # self.typed_attr (data flow within the method)
                            if isinstance(n.value, ast.Name) and n.value.id != "self":
                                var_name = n.value.id
                                for s in ast.walk(item):
                                    if (isinstance(s, ast.Assign)
                                            and len(s.targets) == 1
                                            and isinstance(s.targets[0], ast.Name)
                                            and s.targets[0].id == var_name
                                            and isinstance(s.value, ast.Attribute)
                                            and isinstance(s.value.value, ast.Name)
                                            and s.value.value.id == "self"):
                                        a = s.value.attr
                                        if a in float_attrs:
                                            ret_type = double
                                        elif a in string_attrs:
                                            ret_type = i8_ptr
                                        elif a in bool_attrs:
                                            ret_type = i32
                                        break
                                if ret_type != i64:
                                    break
                            # return local_var[index] where local was assigned
                            # from an expression returning list of strings
                            if (isinstance(n.value, ast.Subscript)
                                    and isinstance(n.value.value, ast.Name)):
                                var_name = n.value.value.id
                                for s in ast.walk(item):
                                    if (isinstance(s, ast.Assign)
                                            and len(s.targets) == 1
                                            and isinstance(s.targets[0], ast.Name)
                                            and s.targets[0].id == var_name):
                                        rhs = s.value
                                        # .split(), .keys(), .values(), .items()
                                        # return list of strings
                                        if (isinstance(rhs, ast.Call)
                                                and isinstance(rhs.func, ast.Attribute)
                                                and rhs.func.attr in (
                                                    "split", "keys", "values",
                                                    "items", "splitlines")):
                                            ret_type = i8_ptr
                                        # List literal of strings
                                        elif (isinstance(rhs, ast.List)
                                                and rhs.elts
                                                and all(isinstance(e, ast.Constant)
                                                        and isinstance(e.value, str)
                                                        for e in rhs.elts)):
                                            ret_type = i8_ptr
                                        break
                                if ret_type != i64:
                                    break
                            # Check for `return cls(...)` inside classmethod — returns obj
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Name)
                                    and n.value.func.id == "cls"):
                                ret_type = i8_ptr
                                break
                            # return self.<list_attr>[slice] — always a list
                            if (isinstance(n.value, ast.Subscript)
                                    and isinstance(n.value.slice, ast.Slice)
                                    and isinstance(n.value.value, ast.Attribute)
                                    and isinstance(n.value.value.value, ast.Name)
                                    and n.value.value.value.id == "self"):
                                attr = n.value.value.attr
                                if attr in list_attrs or attr in string_attrs:
                                    ret_type = i8_ptr
                                    break
                            # return self.<list_attr>[i] — subscript on list attr
                            # Only safe when element type is "str" — other types
                            # (list, dict, obj) need FV ABI which methods don't
                            # use yet.
                            if (isinstance(n.value, ast.Subscript)
                                    and isinstance(n.value.value, ast.Attribute)
                                    and isinstance(n.value.value.value, ast.Name)
                                    and n.value.value.value.id == "self"):
                                attr = n.value.value.attr
                                if attr in list_attrs:
                                    etype = list_attr_elem_types.get(attr)
                                    if etype == "str":
                                        ret_type = i8_ptr
                                        break
                            # return str_method_call
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Attribute)
                                    and n.value.func.attr in (
                                        "upper", "lower", "strip", "lstrip",
                                        "rstrip", "replace", "join", "format")):
                                ret_type = i8_ptr
                                break
                            # Bool-returning: Compare, Not, bool Constant,
                            # BoolOp where all operands are bool-typed.
                            if isinstance(n.value, ast.Compare):
                                ret_type = i32
                                break
                            if (isinstance(n.value, ast.UnaryOp)
                                    and isinstance(n.value.op, ast.Not)):
                                ret_type = i32
                                break
                            if (isinstance(n.value, ast.Constant)
                                    and isinstance(n.value.value, bool)):
                                ret_type = i32
                                break
                            if isinstance(n.value, ast.BoolOp) and all(
                                    isinstance(v, ast.Compare)
                                    or (isinstance(v, ast.UnaryOp)
                                        and isinstance(v.op, ast.Not))
                                    or (isinstance(v, ast.Constant)
                                        and isinstance(v.value, bool))
                                    for v in n.value.values):
                                ret_type = i32
                                break
                            # return int/len/str/float/bool(...) — explicit type wrapper
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Name)):
                                if n.value.func.id in ("int", "len", "abs",
                                                        "ord", "round"):
                                    ret_type = i64
                                    break
                                if n.value.func.id == "float":
                                    ret_type = double
                                    break
                                if n.value.func.id in ("str", "list", "sorted",
                                                        "reversed", "dict"):
                                    ret_type = i8_ptr
                                    break
                                if n.value.func.id in ("bool", "isinstance",
                                                        "any", "all"):
                                    ret_type = i32
                                    break
                                # return ClassName(...) — user class constructor
                                # (include the class currently being declared)
                                if (n.value.func.id in self._user_classes
                                        or n.value.func.id == class_name):
                                    ret_type = i8_ptr
                                    break
                            # return self.<attr> where attr type is known
                            if (isinstance(n.value, ast.Attribute)
                                    and isinstance(n.value.value, ast.Name)
                                    and n.value.value.id == "self"):
                                if n.value.attr in string_attrs:
                                    ret_type = i8_ptr
                                    break
                                if n.value.attr in float_attrs:
                                    ret_type = double
                                    break
                                if n.value.attr in bool_attrs:
                                    ret_type = i32
                                    break
                                if n.value.attr in list_attrs or n.value.attr in dict_attrs:
                                    ret_type = i8_ptr
                                    break
                            # return self.obj_attr.inner_attr — nested attr access
                            if (isinstance(n.value, ast.Attribute)
                                    and isinstance(n.value.value, ast.Attribute)
                                    and isinstance(n.value.value.value, ast.Name)
                                    and n.value.value.value.id == "self"):
                                outer_attr = n.value.value.attr  # self.outer
                                inner_attr = n.value.attr  # .inner
                                obj_types = self._class_obj_attr_types.get(class_name, {})
                                if outer_attr in obj_types:
                                    inner_cls = obj_types[outer_attr]
                                    # Check attr type in the nested class
                                    if inner_attr in self._per_class_float_attrs.get(inner_cls, set()):
                                        ret_type = double
                                        break
                                    if inner_attr in self._per_class_string_attrs.get(inner_cls, set()):
                                        ret_type = i8_ptr
                                        break
                                    if inner_attr in self._per_class_bool_attrs.get(inner_cls, set()):
                                        ret_type = i32
                                        break
                            # return self.dict_attr[key] — dict subscript on self's attr
                            # Only safe for strings (where default subscript path
                            # already returns a pointer; int/float need different
                            # subscript handling that isn't yet implemented here).
                            if (isinstance(n.value, ast.Subscript)
                                    and not isinstance(n.value.slice, ast.Slice)
                                    and isinstance(n.value.value, ast.Attribute)
                                    and isinstance(n.value.value.value, ast.Name)
                                    and n.value.value.value.id == "self"
                                    and n.value.value.attr in dict_attrs):
                                dict_attr_name = n.value.value.attr
                                vtype = self._infer_dict_attr_value_type(
                                    node, dict_attr_name)
                                if vtype == "str":
                                    ret_type = i8_ptr
                                    break
                            # return self.method() — inherit the method's
                            # return type from the current class (or parent).
                            # Check the class being built first (methods
                            # defined earlier in the body), then walk the
                            # parent chain via _user_classes.
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Attribute)
                                    and isinstance(n.value.func.value, ast.Name)
                                    and n.value.func.value.id == "self"):
                                method_called = n.value.func.attr
                                m_ret = None
                                if method_called in methods:
                                    m_ret = methods[method_called].return_value.type
                                else:
                                    cn_lookup = parent_name
                                    while cn_lookup and cn_lookup in self._user_classes:
                                        ci_lookup = self._user_classes[cn_lookup]
                                        if method_called in ci_lookup.methods:
                                            m_ret = ci_lookup.methods[method_called].return_value.type
                                            break
                                        cn_lookup = ci_lookup.parent_name
                                if m_ret is not None and not isinstance(m_ret, ir.VoidType):
                                    ret_type = m_ret
                                    break
                            # return self.obj_attr.method() — nested method call
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Attribute)
                                    and isinstance(n.value.func.value, ast.Attribute)
                                    and isinstance(n.value.func.value.value, ast.Name)
                                    and n.value.func.value.value.id == "self"):
                                outer_attr = n.value.func.value.attr  # self.outer
                                inner_method = n.value.func.attr  # .method (avoid shadow)
                                obj_types = self._class_obj_attr_types.get(class_name, {})
                                if outer_attr in obj_types:
                                    inner_cls = obj_types[outer_attr]
                                    inner_cls_info = self._user_classes.get(inner_cls)
                                    if inner_cls_info and inner_method in inner_cls_info.methods:
                                        inner_ret = inner_cls_info.methods[inner_method].return_value.type
                                        if not isinstance(inner_ret, ir.VoidType):
                                            ret_type = inner_ret
                                            break
                            for sub in ast.walk(n.value):
                                if isinstance(sub, ast.Constant) and isinstance(sub.value, float):
                                    ret_type = double
                                    break
                                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                    ret_type = i8_ptr
                                    break
                                # self.float_attr references
                                if (isinstance(sub, ast.Attribute)
                                        and isinstance(sub.value, ast.Name)
                                        and sub.value.id == "self"
                                        and sub.attr in float_attrs):
                                    ret_type = double
                                    break
                                # self.string_attr references
                                if (isinstance(sub, ast.Attribute)
                                        and isinstance(sub.value, ast.Name)
                                        and sub.value.id == "self"
                                        and sub.attr in string_attrs):
                                    ret_type = i8_ptr
                                    break
                                # Float params from call-site analysis
                                if (isinstance(sub, ast.Name)
                                        and sub.id in float_method_params):
                                    ret_type = double
                                    break

                func_type = ir.FunctionType(ret_type, param_types)
                fn_name = f"fastpy.class.{class_name}.{method_name}"
                func = ir.Function(self.module, func_type, name=fn_name)

                # Inline hint for methods
                func.attributes.add('inlinehint')

                # Name parameters
                for param, pname in zip(func.args, params):
                    param.name = pname

                methods[method_name] = func
                method_asts[method_name] = item

        # Multiple inheritance: flatten secondary-base methods into this
        # class. The primary base is handled via the runtime parent_id
        # chain; secondary bases' methods must be registered directly on
        # this class so they're discoverable by fastpy_find_method.
        for sec_base in secondary_bases:
            sec_info = self._user_classes.get(sec_base)
            if sec_info is None:
                continue
            for m_name, m_func in sec_info.methods.items():
                if m_name not in methods:
                    methods[m_name] = m_func
                    if sec_info.method_asts and m_name in sec_info.method_asts:
                        method_asts[m_name] = sec_info.method_asts[m_name]
            # Inherit container/float/string/bool attrs from secondary bases
            if sec_base in self._class_container_attrs:
                s_list, s_dict = self._class_container_attrs[sec_base]
                list_attrs |= s_list
                dict_attrs |= s_dict
                self._class_container_attrs[class_name] = (list_attrs, dict_attrs)
            self._per_class_float_attrs[class_name] |= self._per_class_float_attrs.get(sec_base, set())
            self._per_class_string_attrs[class_name] |= self._per_class_string_attrs.get(sec_base, set())
            self._per_class_bool_attrs[class_name] |= self._per_class_bool_attrs.get(sec_base, set())

        self._user_classes[class_name] = ClassInfo(
            name=class_name,
            class_id_global=class_id_global,
            methods=methods,
            parent_name=parent_name,
            init_arg_count=init_arg_count,
            init_defaults=init_defaults,
            method_asts=method_asts,
            classmethods=classmethods,
            staticmethods=staticmethods,
            properties=properties,
        )

    def _detect_class_container_attrs(self, node: ast.ClassDef,
                                        cname: str | None = None) -> tuple[set[str], set[str]]:
        """Detect attributes that hold lists or dicts by checking assignments in __init__.

        Returns (list_attrs, dict_attrs). Also populates:
         - `self._class_obj_attrs` with attrs that hold object references
         - `self._class_obj_attr_types` with (class, attr) -> nested class name
        """
        list_attrs: set[str] = set()
        dict_attrs: set[str] = set()
        obj_attrs: set[str] = set()
        obj_attr_types: dict[str, str] = {}
        lookup_name = cname if cname is not None else node.name

        # Find __init__ to analyze param → attr relationships
        init_method = None
        for method in node.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                init_method = method
                break

        # Map __init__ param names → class names (from call-site analysis)
        param_classes: dict[str, str] = {}
        if init_method is not None:
            params = [a.arg for a in init_method.args.args]
            call_types = self._call_site_param_types.get(lookup_name, [])
            # call_types[0] maps to params[1] (skip self)
            # We check obj_classes set during _analyze_call_sites to determine
            # what class each variable passed to __init__ is.
            # Use _csa_constructor_arg_classes if populated.
            arg_classes = getattr(self, '_csa_constructor_arg_classes', {}).get(
                lookup_name, {})
            for arg_idx, cls_name in arg_classes.items():
                pi = arg_idx + 1  # skip self
                if 0 <= pi < len(params):
                    param_classes[params[pi]] = cls_name

        # Scan ALL methods (not just __init__) for `self.attr = <typed>`
        # assignments. Covers patterns like `n.next = other_node` where
        # `next` is later set outside __init__.
        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for n in ast.walk(method):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"):
                            if isinstance(n.value, (ast.List, ast.ListComp, ast.Set)):
                                list_attrs.add(tgt.attr)
                            elif isinstance(n.value, (ast.Dict, ast.DictComp)):
                                dict_attrs.add(tgt.attr)
                            elif (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Name)
                                    and n.value.func.id in self._user_classes):
                                obj_attrs.add(tgt.attr)
                                # self.attr = ClassName(...) — track nested class
                                obj_attr_types[tgt.attr] = n.value.func.id
                            elif (isinstance(n.value, ast.Name)
                                    and n.value.id in param_classes):
                                # self.attr = param where param is a known class
                                obj_attrs.add(tgt.attr)
                                obj_attr_types[tgt.attr] = param_classes[n.value.id]

        # Global pass: scan the WHOLE module for `x.attr = y` patterns
        # where x is an instance of this class and y is either a class
        # constructor call or a known-obj variable. Covers patterns like
        # `n.next = other_n` in external functions that the __init__-scan
        # doesn't see.
        tree = getattr(self, "_csa_root_tree", None)
        if tree is not None:
            # Build a global var → class map for cheap lookup. Uses
            # obj_classes tracked during call-site analysis.
            var_classes_module: dict[str, str] = dict(self._csa_obj_classes)
            # Also add any function-local vars — we scan each function
            # separately below, but for module-level we need the module
            # vars here.
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Attribute)
                        and isinstance(n.targets[0].value, ast.Name)):
                    continue
                receiver_name = n.targets[0].value.id
                attr_name = n.targets[0].attr
                # Self-attr assignments were already handled
                if receiver_name == "self":
                    continue
                # Determine receiver's class
                receiver_cls = var_classes_module.get(receiver_name)
                # Try scoped lookup: find the enclosing function and check
                # local assignments there.
                if receiver_cls is None:
                    # Walk tree for an assignment to receiver_name from a
                    # ClassName(...) call in the same or module scope.
                    for n2 in ast.walk(tree):
                        if (isinstance(n2, ast.Assign) and len(n2.targets) == 1
                                and isinstance(n2.targets[0], ast.Name)
                                and n2.targets[0].id == receiver_name
                                and isinstance(n2.value, ast.Call)
                                and isinstance(n2.value.func, ast.Name)
                                and n2.value.func.id in self._user_classes):
                            receiver_cls = n2.value.func.id
                            break
                if receiver_cls != node.name:
                    continue
                # Determine assigned value's class
                rhs = n.value
                rhs_cls: str | None = None
                if (isinstance(rhs, ast.Call)
                        and isinstance(rhs.func, ast.Name)
                        and rhs.func.id in self._csa_class_asts):
                    rhs_cls = rhs.func.id
                elif isinstance(rhs, ast.Name):
                    rhs_cls = var_classes_module.get(rhs.id)
                    if rhs_cls is None:
                        # Search for a constructor assignment of this name,
                        # or a Name-to-Name chain ending in one (iterative
                        # fixpoint, handles `head = None; head = n` where
                        # n is Node(v)). Uses _csa_class_asts (populated
                        # early) rather than _user_classes (not yet set
                        # for classes currently being declared).
                        known_classes = set(self._csa_class_asts.keys())
                        local_obj: dict[str, str] = {}
                        for _ in range(5):
                            prev = len(local_obj)
                            for n2 in ast.walk(tree):
                                if not (isinstance(n2, ast.Assign) and len(n2.targets) == 1
                                        and isinstance(n2.targets[0], ast.Name)):
                                    continue
                                tgt_name = n2.targets[0].id
                                if (isinstance(n2.value, ast.Call)
                                        and isinstance(n2.value.func, ast.Name)
                                        and n2.value.func.id in known_classes):
                                    local_obj[tgt_name] = n2.value.func.id
                                elif (isinstance(n2.value, ast.Name)
                                      and n2.value.id in local_obj):
                                    local_obj[tgt_name] = local_obj[n2.value.id]
                            if len(local_obj) == prev:
                                break
                        rhs_cls = local_obj.get(rhs.id)
                if rhs_cls is not None:
                    obj_attrs.add(attr_name)
                    obj_attr_types[attr_name] = rhs_cls
                # Also catch `x.attr = None` followed by later `x.attr = Node(...)`
                # The first pass of self.attr=None from __init__ doesn't tag it
                # but external assignments of Node instances do.

        if obj_attrs:
            if not hasattr(self, "_class_obj_attrs"):
                self._class_obj_attrs = {}
            self._class_obj_attrs[lookup_name] = obj_attrs
        if obj_attr_types:
            self._class_obj_attr_types[lookup_name] = obj_attr_types
        return list_attrs, dict_attrs

    def _detect_class_string_attrs(self, node: ast.ClassDef,
                                    cname: str | None = None) -> set[str]:
        """Detect attributes that hold strings by checking assignments."""
        string_attrs = set()

        # First: if Animal("Rex") is called (call-site analysis recorded
        # "str" for a param), and __init__ has `self.attr = param`, then
        # `attr` is a string.
        lookup_name = cname if cname is not None else node.name
        call_types = self._call_site_param_types.get(lookup_name, [])
        # call_types includes self at index 0 for constructors? No — for
        # a class call `Animal("Rex")`, we register the user-visible arity.
        # So arg 0 maps to __init__'s param 1 (name).
        string_param_indices = set()
        for i, t in enumerate(call_types):
            if t == "str":
                string_param_indices.add(i)
        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            if method.name != "__init__":
                continue
            params = [arg.arg for arg in method.args.args]
            # param 0 is self — the call's arg 0 maps to param 1
            str_params = set()
            for i in string_param_indices:
                pi = i + 1
                if 0 <= pi < len(params):
                    str_params.add(params[pi])
            # Find self.attr = str_param
            for n in ast.walk(method):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"
                                and isinstance(n.value, ast.Name)
                                and n.value.id in str_params):
                            string_attrs.add(tgt.attr)

        # Find __init__ and check what types are assigned to self.attr
        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            if method.name != "__init__":
                continue

            params = {arg.arg for arg in method.args.args}
            # Check string defaults
            str_default_params = set()
            defaults = method.args.defaults
            param_list = [arg.arg for arg in method.args.args]
            for i, d in enumerate(defaults):
                idx = len(param_list) - len(defaults) + i
                if isinstance(d, ast.Constant) and isinstance(d.value, str):
                    str_default_params.add(param_list[idx])

            for n in ast.walk(method):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"):
                            # self.attr = "string_constant"
                            if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                                string_attrs.add(tgt.attr)
                            # self.attr = param_with_string_default
                            if isinstance(n.value, ast.Name) and n.value.id in str_default_params:
                                string_attrs.add(tgt.attr)
                            # self.attr = f"..."
                            if isinstance(n.value, ast.JoinedStr):
                                string_attrs.add(tgt.attr)
                            # self.attr = ClassName.CONST (if CONST is a string)
                            if (isinstance(n.value, ast.Attribute)
                                    and isinstance(n.value.value, ast.Name)
                                    and n.value.value.id in self._class_const_attrs):
                                const_val = self._class_const_attrs[n.value.value.id].get(n.value.attr)
                                if (isinstance(const_val, ast.Constant)
                                        and isinstance(const_val.value, str)):
                                    string_attrs.add(tgt.attr)
                            # self.attr = string_concat expression (BinOp with strings)
                            if isinstance(n.value, ast.BinOp):
                                for sub in ast.walk(n.value):
                                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                        string_attrs.add(tgt.attr)
                                        break
                                    if isinstance(sub, ast.JoinedStr):
                                        string_attrs.add(tgt.attr)
                                        break

        return string_attrs

    def _detect_class_float_attrs(self, node: ast.ClassDef,
                                   cname: str | None = None) -> set[str]:
        """Detect attributes that hold floats by checking __init__ assignments."""
        float_attrs: set[str] = set()

        # From call-site analysis: Circle(5.0) registers "float" for arg 0.
        # If __init__ has self.attr = param and param is float, attr is float.
        lookup_name = cname if cname is not None else node.name
        call_types = self._call_site_param_types.get(lookup_name, [])
        float_param_indices = set()
        for i, t in enumerate(call_types):
            if t == "float":
                float_param_indices.add(i)

        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            if method.name != "__init__":
                continue
            params = [arg.arg for arg in method.args.args]
            # param 0 is self — the call's arg 0 maps to param 1
            float_params = set()
            for i in float_param_indices:
                pi = i + 1
                if 0 <= pi < len(params):
                    float_params.add(params[pi])

            # Check float defaults
            defaults = method.args.defaults
            param_list = [arg.arg for arg in method.args.args]
            for i, d in enumerate(defaults):
                idx = len(param_list) - len(defaults) + i
                if isinstance(d, ast.Constant) and isinstance(d.value, float):
                    float_params.add(param_list[idx])

            for n in ast.walk(method):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"):
                            # self.attr = float_constant
                            if isinstance(n.value, ast.Constant) and isinstance(n.value.value, float):
                                float_attrs.add(tgt.attr)
                            # self.attr = float_param
                            if isinstance(n.value, ast.Name) and n.value.id in float_params:
                                float_attrs.add(tgt.attr)
        return float_attrs

    def _infer_dict_attr_value_type(self, class_node: ast.ClassDef,
                                      attr_name: str) -> str | None:
        """Infer the value type of a dict class attribute by scanning all
        methods for self.<attr>[key] = value assignments.

        Returns "str", "float", "int", or None if unknown/mixed.
        """
        seen_types: set[str] = set()
        # Get call-site types for each method in the class so we can
        # determine the types of params used as values.
        for method in class_node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            m_params = [a.arg for a in method.args.args]
            q_key = f"{class_node.name}.{method.name}"
            m_call_types = self._call_site_param_types.get(
                q_key, self._call_site_param_types.get(method.name, []))
            # For __init__, also try the class name (constructor analysis)
            if method.name == "__init__" and not any(m_call_types):
                m_call_types = self._call_site_param_types.get(
                    class_node.name, [])
            param_typed: dict[str, str] = {}
            for i, t in enumerate(m_call_types):
                pi = i + 1  # skip self
                if 0 <= pi < len(m_params) and t:
                    param_typed[m_params[pi]] = t
            for n in ast.walk(method):
                if (isinstance(n, ast.Assign)
                        and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Subscript)
                        and isinstance(n.targets[0].value, ast.Attribute)
                        and isinstance(n.targets[0].value.value, ast.Name)
                        and n.targets[0].value.value.id == "self"
                        and n.targets[0].value.attr == attr_name):
                    rhs = n.value
                    if isinstance(rhs, ast.Constant):
                        if isinstance(rhs.value, str):
                            seen_types.add("str")
                        elif isinstance(rhs.value, bool):
                            seen_types.add("bool")
                        elif isinstance(rhs.value, float):
                            seen_types.add("float")
                        elif isinstance(rhs.value, int):
                            seen_types.add("int")
                    elif isinstance(rhs, ast.JoinedStr):
                        seen_types.add("str")
                    elif isinstance(rhs, ast.Name) and rhs.id in param_typed:
                        seen_types.add(param_typed[rhs.id])
                    elif (isinstance(rhs, ast.BinOp)
                            and (isinstance(rhs.left, ast.Constant)
                                 and isinstance(rhs.left.value, str))):
                        seen_types.add("str")
        if len(seen_types) == 1:
            return next(iter(seen_types))
        return None

    def _detect_class_bool_attrs(self, node: ast.ClassDef,
                                   cname: str | None = None) -> set[str]:
        """Detect attributes that hold booleans by checking __init__ assignments."""
        bool_attrs: set[str] = set()

        # From call-site analysis: Gate(True) registers "bool" for arg 0.
        lookup_name = cname if cname is not None else node.name
        call_types = self._call_site_param_types.get(lookup_name, [])
        bool_param_indices = set()
        for i, t in enumerate(call_types):
            if t == "bool":
                bool_param_indices.add(i)

        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            if method.name != "__init__":
                continue
            params = [arg.arg for arg in method.args.args]
            # param 0 is self — call's arg 0 maps to param 1
            bool_params = set()
            for i in bool_param_indices:
                pi = i + 1
                if 0 <= pi < len(params):
                    bool_params.add(params[pi])
            # Also check bool defaults: def __init__(self, x=True)
            defaults = method.args.defaults
            for di, d in enumerate(defaults):
                pidx = len(params) - len(defaults) + di
                if (isinstance(d, ast.Constant)
                        and isinstance(d.value, bool)
                        and 0 <= pidx < len(params)):
                    bool_params.add(params[pidx])

            for n in ast.walk(method):
                if isinstance(n, ast.Assign):
                    for tgt in n.targets:
                        if (isinstance(tgt, ast.Attribute)
                                and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "self"):
                            # self.attr = True/False
                            if (isinstance(n.value, ast.Constant)
                                    and isinstance(n.value.value, bool)):
                                bool_attrs.add(tgt.attr)
                            # self.attr = bool_param
                            if isinstance(n.value, ast.Name) and n.value.id in bool_params:
                                bool_attrs.add(tgt.attr)
        return bool_attrs

    def _emit_class_methods(self, node: ast.ClassDef,
                             _variant_name: str | None = None) -> None:
        """Generate code for all methods in a class.

        When the class was monomorphized in _declare_class, emit one set
        of method bodies per variant by recursing with the variant name.
        """
        # Top-level: dispatch to variants if monomorphized.
        if _variant_name is None:
            variants = self._monomorphized_classes.get(node.name)
            if variants:
                for sig in variants:
                    mangled = f"{node.name}__{self._mangle_sig(sig)}"
                    self._emit_class_methods(node, _variant_name=mangled)
                return

        effective_name = _variant_name if _variant_name else node.name
        cls_info = self._user_classes[effective_name]
        self._current_class = effective_name
        # Detect string, float, and bool attributes at class level using the
        # variant's call-types so attr typing matches the variant's sig.
        self._class_string_attrs = self._detect_class_string_attrs(
            node, effective_name)
        self._class_float_attrs = self._detect_class_float_attrs(
            node, effective_name)
        self._class_bool_attrs = self._detect_class_bool_attrs(
            node, effective_name)
        # Inherit parent class's string/float/bool attrs for subclass methods
        if cls_info.parent_name:
            self._class_string_attrs |= self._per_class_string_attrs.get(
                cls_info.parent_name, set())
            self._class_float_attrs |= self._per_class_float_attrs.get(
                cls_info.parent_name, set())
            self._class_bool_attrs |= self._per_class_bool_attrs.get(
                cls_info.parent_name, set())
        # Store for subclass inheritance
        self._per_class_float_attrs[effective_name] = set(self._class_float_attrs)
        self._per_class_string_attrs[effective_name] = set(self._class_string_attrs)
        self._per_class_bool_attrs[effective_name] = set(self._class_bool_attrs)

        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_key = item.name
                # @x.setter methods are stored as x__set
                is_setter = any(
                    isinstance(d, ast.Attribute) and d.attr == "setter"
                    for d in item.decorator_list)
                if is_setter:
                    method_key = f"{item.name}__set"
                if method_key in cls_info.methods:
                    func = cls_info.methods[method_key]
                    self._emit_method_body(func, item)
            elif isinstance(item, ast.Pass):
                pass

    def _emit_method_body(self, func: ir.Function, node: ast.FunctionDef) -> None:
        """Generate code for a single method body."""
        saved = (self.function, self.builder, self.variables, self._loop_stack)

        self.function = func
        entry = func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self._loop_stack = []

        # Detect string params, float-default params, and object params
        string_params = self._detect_string_params(node)
        # Detect params with float/bool defaults (e.g. def __init__(self, x=0.0))
        float_default_params: set[str] = set()
        bool_default_params: set[str] = set()
        defaults = node.args.defaults
        params_list = [arg.arg for arg in node.args.args]
        for di, d in enumerate(defaults):
            pidx = len(params_list) - len(defaults) + di
            if isinstance(d, ast.Constant):
                if isinstance(d.value, bool):
                    bool_default_params.add(params_list[pidx])
                elif isinstance(d.value, float):
                    float_default_params.add(params_list[pidx])
        # Detect params used with attribute access (they're objects passed as i64)
        obj_params = set()
        # Detect params that are compared with `is None` / `is not None`.
        # These params can receive None at runtime and need the runtime
        # null-check in _emit_method_body to preserve the NONE tag.
        nullable_params: set[str] = set()
        param_names_set = {arg.arg for arg in node.args.args}
        for n in ast.walk(node):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                pname = n.value.id
                if pname in param_names_set and pname != "self":
                    obj_params.add(pname)
            # `param is None` or `param is not None` → nullable
            if isinstance(n, ast.Compare):
                for comparator, op in zip(
                        [n.left] + n.comparators,
                        n.ops + [None]):
                    if (isinstance(comparator, ast.Name)
                            and comparator.id in param_names_set
                            and comparator.id != "self"):
                        # Check if any comparator/op pair involves None
                        pass
                # Check left `param is None`
                if (isinstance(n.left, ast.Name)
                        and n.left.id in param_names_set
                        and n.left.id != "self"):
                    for op, comp in zip(n.ops, n.comparators):
                        if (isinstance(op, (ast.Is, ast.IsNot))
                                and isinstance(comp, ast.Constant)
                                and comp.value is None):
                            nullable_params.add(n.left.id)
        # Call-site param types for method calls.
        # Try qualified "Class.method" first (avoids cross-class collisions),
        # then fall back to bare method name.
        # For __init__, constructor calls register under the class name.
        # For methods, args[0] is self so call-site types correspond to params[1:].
        qualified = f"{self._current_class}.{node.name}"
        method_call_types = self._call_site_param_types.get(
            qualified, self._call_site_param_types.get(node.name, []))
        if node.name == "__init__":
            # For __init__, prefer the class-name key (from constructor calls
            # like Car(60.0)) over the bare "__init__" key which may contain
            # stale data from parent init calls like Vehicle.__init__(self, x).
            class_types = self._call_site_param_types.get(
                self._current_class, [])
            if class_types:
                method_call_types = class_types

        # Store parameters as local variables. With _USE_FV_LOCALS, most
        # params are wrapped into FpyValue. Classmethod `cls` (i32 class_id)
        # is kept on the legacy bare path because the runtime expects i32.
        # For "mixed" params, the LLVM function has extra args (tag + data).
        method_key = f"{self._current_class}.{node.name}"
        mixed_indices = getattr(self, '_mixed_param_methods', {}).get(method_key, set())
        params = [arg.arg for arg in node.args.args]
        llvm_arg_idx = 0
        for param_idx, pname in enumerate(params):
            if llvm_arg_idx >= len(func.args):
                break
            param = func.args[llvm_arg_idx]
            is_classmethod_cls = (
                isinstance(param.type, ir.IntType) and param.type.width == 32
            )
            if is_classmethod_cls:
                # cls (classmethod) stays as i32 — no FV wrapping
                alloca = self.builder.alloca(param.type, name=pname)
                self.builder.store(param, alloca)
                self.variables[pname] = (alloca, "int")
                llvm_arg_idx += 1
                continue

            # Mixed param: two LLVM args (tag_i64, data_i64) → rebuild fpyvalue
            if param_idx in mixed_indices:
                tag_param = func.args[llvm_arg_idx]
                data_param = func.args[llvm_arg_idx + 1]
                tag_i32 = self.builder.trunc(tag_param, i32)
                fv = self._fv_build_from_slots(tag_i32, data_param)
                alloca = self.builder.alloca(fpy_val, name=pname)
                self.builder.store(fv, alloca)
                self.variables[pname] = (alloca, "int")  # generic tag
                llvm_arg_idx += 2
                continue

            # For non-self params, check call-site analysis (index offset by 1
            # since params[0] is self but method_call_types[0] is the first arg).
            call_idx = param_idx - 1  # skip self
            call_tag = None
            if call_idx >= 0 and call_idx < len(method_call_types):
                call_tag = method_call_types[call_idx]

            if isinstance(param.type, ir.PointerType):
                tag = "obj"
                bare = param
            elif pname in nullable_params and isinstance(param.type, ir.IntType):
                # Param is compared with `is None` in the body — treat as
                # potentially None. The runtime null-check will emit
                # {NONE, 0} when the value is 0.
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = "obj"
                bare = ptr_val
            elif pname in obj_params and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = "obj"
                bare = ptr_val
            elif call_tag == "str" and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = "str"
                bare = ptr_val
            elif call_tag is not None and call_tag.startswith("list") and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = call_tag
                bare = ptr_val
            elif call_tag is not None and call_tag.startswith("dict") and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = "dict"
                bare = ptr_val
            elif call_tag == "float" and isinstance(param.type, ir.IntType):
                dbl_val = self.builder.bitcast(param, double)
                tag = "float"
                bare = dbl_val
            elif pname in float_default_params and isinstance(param.type, ir.IntType):
                dbl_val = self.builder.bitcast(param, double)
                tag = "float"
                bare = dbl_val
            elif call_tag == "obj" and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = "obj"
                bare = ptr_val
            elif call_tag == "bool" and isinstance(param.type, ir.IntType):
                tag = "bool"
                bare = param
            elif pname in bool_default_params and isinstance(param.type, ir.IntType):
                tag = "bool"
                bare = param
            elif pname in string_params and isinstance(param.type, ir.IntType):
                ptr_val = self.builder.inttoptr(param, i8_ptr)
                tag = "str"
                bare = ptr_val
            else:
                tag = "int"
                bare = param

            if self._USE_FV_LOCALS:
                alloca = self.builder.alloca(fpy_val, name=pname)
                # For obj-tagged params passed as i64, a runtime value of 0
                # means None (the caller passed None as i64(0)). Emit a
                # branch so the FV gets NONE tag instead of OBJ tag with a
                # null pointer. Without this, `self.attr = param` stores
                # {OBJ, 0} and `obj.attr is None` returns False.
                if tag == "obj" and isinstance(param.type, ir.IntType):
                    is_null = self.builder.icmp_unsigned(
                        "==", param, ir.Constant(param.type, 0))
                    fv_none = self._fv_none()
                    fv_obj = self._wrap_bare_to_fv(bare, "obj")
                    fv = self.builder.select(is_null, fv_none, fv_obj)
                    self.builder.store(fv, alloca)
                    self.variables[pname] = (alloca, tag)
                    llvm_arg_idx += 1
                    continue
                fv = self._wrap_bare_to_fv(bare, tag)
                self.builder.store(fv, alloca)
            else:
                alloca = self.builder.alloca(bare.type, name=pname)
                self.builder.store(bare, alloca)
            self.variables[pname] = (alloca, tag)
            llvm_arg_idx += 1

        # Emit body
        self._emit_stmts(node.body)

        if not self.builder.block.is_terminated:
            if func.return_value.type == void:
                self.builder.ret_void()
            elif isinstance(func.return_value.type, ir.PointerType):
                # String return — return empty string as default
                default_str = self._make_string_constant("")
                self.builder.ret(default_str)
            else:
                self.builder.ret(ir.Constant(func.return_value.type, 0))

        self.function, self.builder, self.variables, self._loop_stack = saved

    def _emit_class_registration(self, cls_info: ClassInfo) -> None:
        """Emit runtime calls to register a class and its methods."""
        # Get parent class_id
        if cls_info.parent_name and cls_info.parent_name in self._user_classes:
            parent_info = self._user_classes[cls_info.parent_name]
            parent_id = self.builder.load(parent_info.class_id_global)
            parent_id = self.builder.sext(parent_id, i32)  # already i32
        else:
            parent_id = ir.Constant(i32, -1)

        # Register class: class_id = register_class(name, parent_id)
        name_ptr = self._make_string_constant(cls_info.name)
        class_id = self.builder.call(
            self.runtime["register_class"], [name_ptr, parent_id]
        )
        self.builder.store(class_id, cls_info.class_id_global)

        # Set slot count so obj_new allocates the right storage
        slots = self._class_attr_slots.get(cls_info.name, {})
        if slots:
            self.builder.call(self.runtime["set_class_slot_count"], [
                class_id, ir.Constant(i32, len(slots))
            ])
            # Register slot names only if something in the program needs
            # name-based lookup (getattr, dir, vars, unknown receivers, etc.).
            # When every attribute access is statically resolved, names are
            # pure overhead.
            if getattr(self, '_slot_names_needed', True):
                for attr_name, slot_idx in slots.items():
                    name_ptr = self._make_string_constant(attr_name)
                    self.builder.call(self.runtime["register_slot_name"], [
                        class_id, ir.Constant(i32, slot_idx), name_ptr
                    ])

        # Register each method
        for method_name, method_func in cls_info.methods.items():
            mname_ptr = self._make_string_constant(method_name)
            # Cast function pointer to i8*
            func_ptr = self.builder.bitcast(method_func, i8_ptr)
            # Argument count (excluding self)
            n_args = len(method_func.args) - 1  # minus self
            returns = 0 if method_func.return_value.type == void else 1
            self.builder.call(self.runtime["register_method"], [
                class_id, mname_ptr, func_ptr,
                ir.Constant(i32, n_args),
                ir.Constant(i32, returns),
            ])

    def _emit_stmt(self, node: ast.stmt) -> None:
        """Emit LLVM IR for a statement."""
        # Yield statements: must come before generic Expr handler
        if (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Yield)):
            self._emit_yield(node.value)
            return
        if (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.YieldFrom)):
            self._emit_yield_from(node.value)
            return
        if isinstance(node, ast.Expr):
            self._emit_expr_stmt(node)
        elif isinstance(node, ast.Assign):
            self._emit_assign(node)
        elif isinstance(node, ast.AugAssign):
            self._emit_aug_assign(node)
        elif isinstance(node, ast.If):
            self._emit_if(node)
        elif isinstance(node, ast.While):
            self._emit_while(node)
        elif isinstance(node, ast.For):
            self._emit_for(node)
        elif isinstance(node, ast.Break):
            self._emit_break(node)
        elif isinstance(node, ast.Continue):
            self._emit_continue(node)
        elif isinstance(node, ast.Pass):
            pass  # no-op
        elif isinstance(node, ast.Return):
            self._emit_return(node)
        elif isinstance(node, ast.FunctionDef):
            self._emit_nested_funcdef(node)
        elif isinstance(node, ast.Nonlocal):
            pass  # handled implicitly by closure capture
        elif isinstance(node, ast.Global):
            # Mark variables as global — they use module-level globals
            for name in node.names:
                if name in self._global_vars:
                    self.variables[name] = self._global_vars[name]
        elif isinstance(node, ast.ClassDef):
            pass  # already handled in generate()
        elif isinstance(node, ast.Try):
            self._emit_try(node)
        elif isinstance(node, ast.Raise):
            self._emit_raise(node)
        elif isinstance(node, ast.Assert):
            self._emit_assert(node)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                self._emit_delete(target, node)
        elif isinstance(node, ast.With):
            self._emit_with(node)
        elif isinstance(node, ast.Match):
            self._emit_match(node)
        elif isinstance(node, ast.Import):
            self._emit_import(node)
        elif isinstance(node, ast.ImportFrom):
            self._emit_import_from(node)
        elif isinstance(node, ast.AsyncFunctionDef):
            self._emit_async_funcdef(node)
        elif isinstance(node, ast.TryStar):
            self._emit_try_star(node)
        elif isinstance(node, ast.AnnAssign):
            # Type-annotated assignment: x: int = expr → ignore annotation
            if node.value is not None and node.target is not None:
                # Treat as regular assignment
                fake = ast.Assign(targets=[node.target], value=node.value)
                ast.copy_location(fake, node)
                self._emit_assign(fake)
            # Bare annotation (x: int) with no value — skip
        else:
            raise CodeGenError(f"Unsupported statement: {type(node).__name__}", node)

    def _emit_delete(self, target: ast.expr, node: ast.AST) -> None:
        """Emit `del target` — removes item from list/dict."""
        if isinstance(target, ast.Subscript):
            container = self._emit_expr_value(target.value)
            key = self._emit_expr_value(target.slice)
            if self._is_dict_expr(target.value):
                self.builder.call(self.runtime["dict_delete"], [container, key])
            elif self._is_list_expr(target.value):
                self.builder.call(self.runtime["list_delete_at"], [container, key])
            elif self._is_obj_expr(target.value):
                obj_cls = self._infer_object_class(target.value)
                if obj_cls and self._class_has_method(obj_cls, "__delitem__"):
                    if isinstance(container.type, ir.IntType):
                        container = self.builder.inttoptr(container, i8_ptr)
                    if isinstance(key.type, ir.PointerType):
                        key = self.builder.ptrtoint(key, i64)
                    elif isinstance(key.type, ir.IntType) and key.type.width != 64:
                        key = self.builder.zext(key, i64)
                    name_ptr = self._make_string_constant("__delitem__")
                    self.builder.call(self.runtime["obj_call_method1"],
                                      [container, name_ptr, key])
                else:
                    raise CodeGenError("del on unsupported container type", node)
            else:
                raise CodeGenError("del on unsupported container type", node)
        elif isinstance(target, ast.Name):
            # del variable — just remove from scope (CPython raises NameError on later use)
            pass  # No-op for now; the variable stays in scope but could be undefined
        else:
            raise CodeGenError(f"del with {type(target).__name__} target not supported", node)

    def _emit_assert(self, node: ast.Assert) -> None:
        """Emit an assert statement: if not <test>: raise AssertionError."""
        cond = self._emit_expr_value(node.test)
        # Coerce to i1
        if isinstance(cond.type, ir.IntType) and cond.type.width != 1:
            cond = self.builder.icmp_signed("!=", cond, ir.Constant(cond.type, 0))
        elif isinstance(cond.type, ir.PointerType):
            # Non-null pointer is truthy
            null_ptr = ir.Constant(cond.type, None)
            cond = self.builder.icmp_unsigned("!=", cond, null_ptr)
        elif isinstance(cond.type, ir.DoubleType):
            cond = self.builder.fcmp_ordered("!=", cond, ir.Constant(double, 0.0))

        pass_block = self._new_block("assert.pass")
        fail_block = self._new_block("assert.fail")
        self.builder.cbranch(cond, pass_block, fail_block)

        self.builder.position_at_end(fail_block)
        # Raise AssertionError
        msg_str = ""
        if node.msg is not None:
            if isinstance(node.msg, ast.Constant) and isinstance(node.msg.value, str):
                msg_str = node.msg.value
        msg_ptr = self._make_string_constant(msg_str)
        name_ptr = self._make_string_constant("AssertionError")
        exc_id = self.builder.call(self.runtime["exc_name_to_id"], [name_ptr])
        self.builder.call(self.runtime["raise"], [exc_id, msg_ptr])
        # If not in try block, return early (exception will propagate to main)
        if not self._in_try_block:
            ret_type = self.function.return_value.type
            if isinstance(ret_type, ir.VoidType):
                self.builder.ret_void()
            elif isinstance(ret_type, ir.LiteralStructType):
                self.builder.ret(self._fv_none())
            elif isinstance(ret_type, ir.DoubleType):
                self.builder.ret(ir.Constant(double, 0.0))
            elif isinstance(ret_type, ir.PointerType):
                self.builder.ret(ir.Constant(ret_type, None))
            else:
                self.builder.ret(ir.Constant(i64, 0))
        else:
            self.builder.branch(pass_block)

        self.builder.position_at_end(pass_block)

    def _emit_expr_stmt(self, node: ast.Expr) -> None:
        """Emit an expression statement (e.g., print(...))."""
        expr = node.value
        if isinstance(expr, ast.Call):
            self._emit_call(expr)
        else:
            # Expression with no side effect — skip it
            pass

    def _emit_assign(self, node: ast.Assign) -> None:
        """Emit a variable assignment: x = expr, or tuple unpacking: a, b = 1, 2"""
        # Handle tuple unpacking: a, b, c = expr
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple):
            self._emit_tuple_unpack(node.targets[0], node.value, node)
            return

        # Lambda assignments are handled in the declaration pass — skip
        if isinstance(node.value, ast.Lambda):
            return

        # CPython module attribute or method result: use _load_or_wrap_fv
        # to get a proper FpyValue with the runtime tag from the bridge.
        if (self._USE_FV_LOCALS
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            rhs = node.value
            is_pyobj_attr = (isinstance(rhs, ast.Attribute)
                             and isinstance(rhs.value, ast.Name)
                             and rhs.value.id in self.variables
                             and self.variables[rhs.value.id][1] == "pyobj")
            is_pyobj_call = (isinstance(rhs, ast.Call)
                             and isinstance(rhs.func, ast.Attribute)
                             and isinstance(rhs.func.value, ast.Name)
                             and rhs.func.value.id in self.variables
                             and self.variables[rhs.func.value.id][1] == "pyobj")
            is_pyobj_direct = (isinstance(rhs, ast.Call)
                               and isinstance(rhs.func, ast.Name)
                               and rhs.func.id in self.variables
                               and self.variables[rhs.func.id][1] == "pyobj")
            if is_pyobj_attr or is_pyobj_call or is_pyobj_direct:
                if is_pyobj_direct:
                    # Direct call: g() where g is a CPython function.
                    # Store result as pyobj for method calls on the result.
                    val = self._emit_expr_value(rhs)
                    if isinstance(val.type, ir.IntType):
                        val = self.builder.inttoptr(val, i8_ptr)
                    self._store_variable(node.targets[0].id, val, "pyobj")
                    return
                # Method call (math.sqrt()) or attribute (math.pi):
                # Store the raw PyObject* as pyobj so downstream operations
                # (method calls, subscript, len, int(), print) all route
                # through the CPython bridge with correct type semantics.
                if is_pyobj_call:
                    pyobj_ptr = self._emit_cpython_call_raw(rhs)
                else:
                    # Attribute access: get the raw PyObject*
                    obj = self._load_variable(rhs.value.id, rhs)
                    if isinstance(obj.type, ir.IntType):
                        obj = self.builder.inttoptr(obj, i8_ptr)
                    attr_name = self._make_string_constant(rhs.attr)
                    pyobj_ptr = self.builder.call(
                        self.runtime["cpython_getattr"], [obj, attr_name])
                self._store_variable(node.targets[0].id, pyobj_ptr, "pyobj")
                return

        # For FV-ABI user function calls that may return None, store the raw
        # FpyValue directly to preserve the runtime tag. This avoids the
        # unwrap/re-wrap cycle that loses the NONE tag. Only applies when the
        # function is known to have a `return None` path — other functions
        # (closures, single-type returns) use the normal unwrap flow.
        if (self._USE_FV_LOCALS
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in self._user_functions):
            # Resolve specialization for correct ret_tag (int vs float etc.)
            lookup_name = node.value.func.id
            if lookup_name in self._monomorphized:
                lookup_name = self._resolve_specialization(
                    lookup_name, node.value.args, node.value.keywords)
            info = self._user_functions[lookup_name]
            if (info.uses_fv_abi and info.ret_tag != "void"
                    and info.may_return_none):
                fv = self._emit_user_call_fv(node.value)
                type_tag = info.ret_tag
                self._store_variable(node.targets[0].id, fv, type_tag)
                return

        # Fast path for Attribute RHS on an object receiver: use
        # _load_or_wrap_fv to preserve the runtime tag. Any attribute on
        # a user-class object might hold None (from `self.attr = None` in
        # __init__), so we need the full tag+data read — the data-only
        # optimization in _emit_attr_load would stamp OBJ tag even when
        # the slot actually holds NONE, breaking `is None` checks.
        # Broadened from the original `_is_obj_expr(node.value)` check
        # (which missed cases where the attr wasn't recognized as obj
        # but the receiver was) to catch any attr access on an obj
        # receiver.
        if (self._USE_FV_LOCALS
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Attribute)
                and (self._is_obj_expr(node.value)
                     or self._is_obj_expr(node.value.value))):
            # Emit the attr expression as FV (preserves runtime tag, so
            # NONE sentinels from uninitialized slots roundtrip correctly).
            fv = self._load_or_wrap_fv(node.value)
            type_tag = "obj"
            target_name = node.targets[0].id
            self._store_variable(target_name, fv, type_tag)
            # Propagate class for downstream attr accesses
            cls = self._infer_object_class(node.value)
            if cls:
                self._obj_var_class[target_name] = cls
            return

        value = self._emit_expr_value(node.value)
        type_tag = self._infer_type_tag(node.value, value)

        # CPython bridge builtin result: tag as "pyobj" so downstream
        # ops (len, in, for) route through the bridge.
        if (isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id not in self._user_functions
                and node.value.func.id not in self._user_classes
                and node.value.func.id not in self.variables
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            builtin_name = node.value.func.id
            # Known fastpy builtins that return native types — don't tag as pyobj
            native_builtins = {
                "len", "int", "float", "str", "bool", "abs", "sum",
                "min", "max", "range", "sorted", "reversed", "list",
                "set", "enumerate", "zip", "isinstance", "type",
                "any", "all", "chr", "ord", "hex", "oct", "bin",
                "round", "repr", "pow", "divmod", "dict", "tuple",
                "map", "filter", "hash", "print",
            }
            if builtin_name not in native_builtins:
                type_tag = "pyobj"

        # When a closure returns a value that will be called later,
        # we need to detect whether it's a closure or raw function pointer.
        # For now, closures that capture variables (from _emit_nested_funcdef)
        # are tagged "closure". Hoisted functions (no captures) remain as
        # "int" (raw function pointer) and are called via call_ptr0.

        # If assigning an empty list and pre-scan detected the actual element type,
        # override the default "list:int" tag
        if (type_tag == "list:int" and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            target_name = node.targets[0].id
            if target_name in self._list_append_types:
                type_tag = f"list:{self._list_append_types[target_name]}"

        # Track tuple element types for subscript dispatch
        if (type_tag == "tuple" and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Tuple) and node.value.elts):
            elts = node.value.elts
            if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts):
                self._tuple_elem_types[node.targets[0].id] = "str"
            elif all(isinstance(e, ast.Constant) and isinstance(e.value, float) for e in elts):
                self._tuple_elem_types[node.targets[0].id] = "float"

        # Track class name for object variables
        class_name = None
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            if node.value.func.id in self._user_classes:
                class_name = node.value.func.id
                # Resolve to variant if the class is monomorphized so
                # downstream method dispatch finds the right variant.
                if class_name in self._monomorphized_classes:
                    class_name = self._resolve_class_specialization(
                        class_name, node.value.args, node.value.keywords)
        elif isinstance(node.value, ast.Call):
            class_name = self._infer_object_class(node.value)
        elif isinstance(node.value, ast.Name):
            # Propagate obj class through `cur = head` aliases.
            if node.value.id in self._obj_var_class:
                class_name = self._obj_var_class[node.value.id]
        elif isinstance(node.value, ast.Attribute):
            # `cur = cur.next` — propagate class from attr type.
            attr_cls = self._infer_object_class(node.value)
            if attr_cls:
                class_name = attr_cls

        # Track dict variables whose values are all lists / all ints /
        # all dicts / all objects. Used by _emit_subscript to choose how
        # to unwrap `d[k]` to a bare LLVM type.
        has_list_values = False
        has_int_values = False
        has_dict_values = False
        has_obj_values = False
        if isinstance(node.value, ast.Dict) and node.value.values:
            has_list_values = all(
                isinstance(v, (ast.List, ast.ListComp)) for v in node.value.values
            )
            has_dict_values = all(
                isinstance(v, (ast.Dict, ast.DictComp)) for v in node.value.values
            )
            has_int_values = all(
                isinstance(v, ast.Constant) and isinstance(v.value, (int, bool))
                and not isinstance(v.value, bool)  # exclude bool specifically
                for v in node.value.values
            )
            has_obj_values = all(
                self._is_obj_expr(v) for v in node.value.values
            )
        # Propagate dict-value-type flag through function returns: if the
        # callee returns a dict literal with all-int / all-list values,
        # treat the assignment target the same way.
        elif (isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in self._user_functions):
            fn_def = self._function_def_nodes.get(node.value.func.id)
            if fn_def is not None:
                ret_dict = self._find_returned_dict_literal(fn_def)
                if ret_dict is not None and ret_dict.values:
                    has_list_values = all(
                        isinstance(v, (ast.List, ast.ListComp)) for v in ret_dict.values
                    )
                    has_int_values = all(
                        isinstance(v, ast.Constant)
                        and isinstance(v.value, (int, bool))
                        and not isinstance(v.value, bool)
                        for v in ret_dict.values
                    )

        # For dict literals with string keys and mixed values, build a
        # per-key type map so `d["age"]` returns an int while `d["name"]`
        # returns a string. Enables mixed-type dict filtering in list
        # comprehensions and similar idioms.
        dict_key_types: dict[str, str] = {}
        if isinstance(node.value, ast.Dict):
            for k_node, v_node in zip(node.value.keys, node.value.values):
                if not (isinstance(k_node, ast.Constant)
                        and isinstance(k_node.value, str)):
                    continue
                t = self._infer_constant_value_type(v_node)
                if t is not None:
                    dict_key_types[k_node.value] = t

        for target in node.targets:
            if isinstance(target, ast.Name):
                self._store_variable(target.id, value, type_tag)
                if class_name:
                    self._obj_var_class[target.id] = class_name
                if has_list_values:
                    self._dict_var_list_values.add(target.id)
                if has_dict_values:
                    self._dict_var_dict_values.add(target.id)
                if has_int_values:
                    self._dict_var_int_values.add(target.id)
                if has_obj_values:
                    self._dict_var_obj_values.add(target.id)
                if dict_key_types:
                    self._dict_var_key_types[target.id] = dict_key_types
            elif isinstance(target, ast.Attribute):
                self._emit_attr_store(target, value, node, value_node=node.value)
            elif isinstance(target, ast.Subscript):
                # Track dict value types through subscript assignments so
                # nested access like d["a"]["x"] knows d["a"] returns a dict.
                if (isinstance(target.value, ast.Name)
                        and self._is_dict_expr(target.value)):
                    base_name = target.value.id
                    if isinstance(node.value, (ast.Dict, ast.DictComp)):
                        self._dict_var_dict_values.add(base_name)
                    elif isinstance(node.value, (ast.List, ast.ListComp)):
                        self._dict_var_list_values.add(base_name)
                    elif (isinstance(node.value, ast.Constant)
                          and isinstance(node.value.value, int)
                          and not isinstance(node.value.value, bool)):
                        self._dict_var_int_values.add(base_name)
                self._emit_subscript_store(target, value, node,
                                           value_node=node.value)
            else:
                raise CodeGenError(
                    f"Unsupported assignment target: {type(target).__name__}",
                    node,
                )

    def _emit_attr_load(self, node: ast.Attribute) -> ir.Value:
        """Emit obj.x attribute load via FV-ABI obj_get_fv.

        Returns a bare value (not FpyValue) of the type expected by callers,
        determined by AST-level container-attribute detection. Since obj_get_fv
        stores the exact tag, this works without the old pointer-heuristic.
        """
        # Nested class chained access: Outer.Inner.x
        # The AST is Attribute(Attribute(Name("Outer"), "Inner"), "x")
        if (isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id in self._user_classes
                and node.value.attr in self._user_classes):
            inner_class = node.value.attr
            # Resolve x from the inner class
            key = (inner_class, node.attr)
            if key in getattr(self, "_class_var_globals", {}):
                gvar, _tag = self._class_var_globals[key]
                return self.builder.load(gvar)
            const_attrs = self._class_const_attrs.get(inner_class, {})
            if node.attr in const_attrs:
                return self._emit_expr_value(const_attrs[node.attr])
            raise CodeGenError(
                f"Nested class {inner_class} has no attribute {node.attr}",
                node)

        # Class-level constant access: ClassName.ATTR
        if (isinstance(node.value, ast.Name)
                and node.value.id in self._user_classes):
            class_name = node.value.id
            # Mutable class var — load from the LLVM global
            key = (class_name, node.attr)
            if key in getattr(self, "_class_var_globals", {}):
                gvar, _tag = self._class_var_globals[key]
                return self.builder.load(gvar)
            const_attrs = self._class_const_attrs.get(class_name, {})
            if node.attr in const_attrs:
                return self._emit_expr_value(const_attrs[node.attr])
            # Nested class reference: A.B → return placeholder for chaining
            if node.attr in self._user_classes:
                return ir.Constant(i64, 0)
            raise CodeGenError(
                f"Class {class_name} has no class-level attribute {node.attr}",
                node,
            )
        # @property dispatch: if this attr is a property-decorated method,
        # call the getter instead of reading a slot.
        obj_cls = self._infer_object_class(node.value)
        if obj_cls:
            cls_info = self._user_classes.get(obj_cls)
            if cls_info and cls_info.properties and node.attr in cls_info.properties:
                obj = self._emit_expr_value(node.value)
                if isinstance(obj.type, ir.IntType):
                    obj = self.builder.inttoptr(obj, i8_ptr)
                method_func = cls_info.methods.get(node.attr)
                if method_func:
                    # Direct dispatch to property getter
                    return self.builder.call(method_func, [obj])
                # Fallback to runtime dispatch
                name_ptr = self._make_string_constant(node.attr)
                return self.builder.call(
                    self.runtime["obj_call_method0"], [obj, name_ptr])

        obj = self._emit_expr_value(node.value)
        # Attribute access always operates on an object pointer.  When the
        # object comes from an FV-backed variable with "int" tag (before the
        # call-site "obj" fix), the data is i64.  Convert to i8* so that
        # obj_get_fv receives the correct pointer type.
        if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
            obj = self.builder.inttoptr(obj, i8_ptr, name="obj.ptr")
        attr_name = self._make_string_constant(node.attr)

        # Try static slot fast path first — direct GEP IR skips the
        # fastpy_obj_get_slot call overhead. Since the caller only uses
        # the data (type is inferred statically from the attr's class),
        # emit a data-only load (Phase 9: skip unused tag load).
        slot_idx = self._get_attr_slot(node)
        if slot_idx is not None:
            data_i64 = self._emit_slot_get_data_only(obj, slot_idx)
        else:
            # Fall back to FV-ABI getter with name lookup
            tag_slot = self._create_entry_alloca(i32, "attr.tag")
            data_slot = self._create_entry_alloca(i64, "attr.data")
            self.builder.call(self.runtime["obj_get_fv"],
                              [obj, attr_name, tag_slot, data_slot])
            data_i64 = self.builder.load(data_slot)

        # Decide the bare type expected by the caller, based on AST inference
        obj_cls = self._infer_object_class(node.value)
        is_container = False
        if obj_cls and obj_cls in self._class_container_attrs:
            list_attrs, dict_attrs = self._class_container_attrs[obj_cls]
            if node.attr in list_attrs or node.attr in dict_attrs:
                is_container = True

        # Prefer per-class attr info when we know the object's class (covers
        # nested attribute access like self.pos.x where pos is a Position).
        if obj_cls and obj_cls in self._per_class_string_attrs:
            class_str_attrs = self._per_class_string_attrs.get(obj_cls, set())
        else:
            class_str_attrs = getattr(self, '_class_string_attrs', set())
        is_str = node.attr in class_str_attrs

        if obj_cls and obj_cls in self._per_class_float_attrs:
            class_float_attrs = self._per_class_float_attrs.get(obj_cls, set())
        else:
            class_float_attrs = getattr(self, '_class_float_attrs', set())
        is_float = node.attr in class_float_attrs

        class_obj_attrs_all = getattr(self, '_class_obj_attrs', {})
        is_obj_attr = False
        if obj_cls and obj_cls in class_obj_attrs_all:
            if node.attr in class_obj_attrs_all[obj_cls]:
                is_obj_attr = True

        if is_container or is_str or is_obj_attr:
            # Return as i8* — pointer (either list/dict/obj pointer or string)
            return self.builder.inttoptr(data_i64, i8_ptr)
        if is_float:
            # Return as double — bitcast i64 data back to double
            return self.builder.bitcast(data_i64, double)
        # Default: return as i64 (int)
        return data_i64

    def _emit_subscript_store(self, target: ast.Subscript, value: ir.Value,
                              node: ast.AST,
                              value_node: ast.expr | None = None) -> None:
        """Emit list[idx] = value or dict[key] = value via FV-ABI setters."""
        # Slice assignment: a[start:stop] = new_values
        if isinstance(target.slice, ast.Slice):
            obj = self._emit_expr_value(target.value)
            if isinstance(obj.type, ir.IntType):
                obj = self.builder.inttoptr(obj, i8_ptr)
            slc = target.slice
            if slc.lower is not None:
                start = self._emit_expr_value(slc.lower)
            else:
                start = ir.Constant(i64, 0)
            if slc.upper is not None:
                stop = self._emit_expr_value(slc.upper)
            else:
                length = self.builder.call(self.runtime["list_length"], [obj])
                stop = length
            if isinstance(value.type, ir.IntType):
                value = self.builder.inttoptr(value, i8_ptr)
            self.builder.call(self.runtime["list_slice_assign"],
                              [obj, start, stop, value])
            return
        # __setitem__ on user-class objects
        if self._is_obj_expr(target.value):
            obj_cls = self._infer_object_class(target.value)
            if obj_cls and self._class_has_method(obj_cls, "__setitem__"):
                obj = self._emit_expr_value(target.value)
                if isinstance(obj.type, ir.IntType):
                    obj = self.builder.inttoptr(obj, i8_ptr)
                key = self._emit_expr_value(target.slice)
                if isinstance(key.type, ir.PointerType):
                    key = self.builder.ptrtoint(key, i64)
                elif isinstance(key.type, ir.IntType) and key.type.width != 64:
                    key = self.builder.zext(key, i64)
                if isinstance(value.type, ir.PointerType):
                    value = self.builder.ptrtoint(value, i64)
                elif isinstance(value.type, ir.IntType) and value.type.width != 64:
                    value = self.builder.zext(value, i64)
                name_ptr = self._make_string_constant("__setitem__")
                self.builder.call(self.runtime["obj_call_method2"],
                                  [obj, name_ptr, key, value])
                return
        obj = self._emit_expr_value(target.value)
        index = self._emit_expr_value(target.slice)
        tag, data = self._bare_to_tag_data(value, value_node=value_node)
        if self._is_dict_expr(target.value):
            # Int keys use the int-keyed setter so the dict stores them
            # natively (vs converting to strings, which would affect
            # printed representation).
            if isinstance(index.type, ir.IntType):
                self.builder.call(self.runtime["dict_set_int_fv"],
                                  [obj, index, ir.Constant(i32, tag), data])
            else:
                if not isinstance(index.type, ir.PointerType):
                    raise CodeGenError("Dict access with non-string key not yet supported", node)
                self.builder.call(self.runtime["dict_set_fv"],
                                  [obj, index, ir.Constant(i32, tag), data])
        else:
            # List set: index must be int
            self.builder.call(self.runtime["list_set_fv"],
                              [obj, index, ir.Constant(i32, tag), data])

    def _bare_to_tag_data(self, value: ir.Value,
                            value_node: ast.expr | None = None) -> tuple[int, ir.Value]:
        """Convert a bare LLVM value into a (tag, i64_data) pair for FV calls.

        When `value_node` is provided, it disambiguates pointer values
        between STR/LIST/DICT/OBJ tags (otherwise pointers default to STR).
        """
        if isinstance(value.type, ir.IntType):
            if value.type.width == 32:
                return FPY_TAG_BOOL, self.builder.zext(value, i64)
            if value.type.width == 64:
                # Call to pyobj-tagged function: result is a PyObject*
                # (packed as i64). Tag as OBJ so the CPython bridge passes
                # it through correctly rather than treating as an integer.
                if (value_node is not None
                        and isinstance(value_node, ast.Call)
                        and isinstance(value_node.func, ast.Name)
                        and value_node.func.id in self.variables
                        and self.variables[value_node.func.id][1] == "pyobj"):
                    return FPY_TAG_OBJ, value
                # User function used as a value (e.g. threading.Thread(target=worker)):
                # wrap as CPython callable so the bridge can call it back.
                if (value_node is not None
                        and isinstance(value_node, ast.Name)
                        and value_node.id in self._user_functions
                        and value_node.id not in self.variables):
                    func_ptr = self.builder.inttoptr(value, i8_ptr)
                    wrapped = self.builder.call(
                        self.runtime["cpython_wrap_native"], [func_ptr])
                    return FPY_TAG_OBJ, self.builder.ptrtoint(wrapped, i64)
                # CPython method call result (e.g. np.array([1,2]) as arg):
                # tag as OBJ so the bridge passes the PyObject* through.
                if (value_node is not None
                        and isinstance(value_node, ast.Call)
                        and isinstance(value_node.func, ast.Attribute)
                        and isinstance(value_node.func.value, ast.Name)
                        and value_node.func.value.id in self.variables
                        and self.variables[value_node.func.value.id][1] == "pyobj"):
                    return FPY_TAG_OBJ, value
                # Check value_node for bool constants (emitted as i64, not
                # i32) and bool-typed variables so the BOOL tag is preserved.
                if value_node is not None:
                    if (isinstance(value_node, ast.Constant)
                            and isinstance(value_node.value, bool)):
                        return FPY_TAG_BOOL, value
                    if (isinstance(value_node, ast.Name)
                            and value_node.id in self.variables
                            and self.variables[value_node.id][1] == "bool"):
                        return FPY_TAG_BOOL, value
                    if isinstance(value_node, ast.Compare):
                        return FPY_TAG_BOOL, value
                    if self._is_bool_typed(value_node):
                        return FPY_TAG_BOOL, value
                return FPY_TAG_INT, value
            # Odd-width int — zext/trunc to i64
            if value.type.width < 64:
                return FPY_TAG_INT, self.builder.zext(value, i64)
            return FPY_TAG_INT, self.builder.trunc(value, i64)
        if isinstance(value.type, ir.DoubleType):
            return FPY_TAG_FLOAT, self.builder.bitcast(value, i64)
        if isinstance(value.type, ir.PointerType):
            tag = FPY_TAG_STR
            if value_node is not None:
                if self._is_list_expr(value_node) or self._is_tuple_expr(value_node):
                    tag = FPY_TAG_LIST
                elif self._is_dict_expr(value_node):
                    tag = FPY_TAG_DICT
                elif self._is_obj_expr(value_node):
                    tag = FPY_TAG_OBJ
                elif self._is_set_expr(value_node):
                    tag = FPY_TAG_SET
                elif (isinstance(value_node, ast.Constant)
                      and isinstance(value_node.value, bytes)):
                    tag = FPY_TAG_BYTES
                elif (isinstance(value_node, ast.Name)
                      and value_node.id in self.variables
                      and self.variables[value_node.id][1] == "pyobj"):
                    tag = FPY_TAG_OBJ
            return tag, self.builder.ptrtoint(value, i64)
        raise CodeGenError(f"Cannot encode {value.type} as FpyValue")

    def _get_attr_slot(self, attr_node: ast.Attribute) -> int | None:
        """Return the static slot index for an obj.attr reference, or None
        if the object's class can't be determined or the attr isn't known.
        """
        obj_cls = self._infer_object_class(attr_node.value)
        if not obj_cls:
            return None
        slots = self._class_attr_slots.get(obj_cls)
        if not slots:
            return None
        return slots.get(attr_node.attr)

    # Constants for direct slot offset computation (must match C layout).
    # FpyObj: { i32 class_id, 4 pad, i8* slots, i8* dynamic_attrs } = 24 bytes
    # FpyValue: { i32 tag, 4 pad, i64 data } = 16 bytes
    _FPYOBJ_SIZE = 32    # sizeof(FpyObj) on x64 (excl lock): refcount(4) + magic(4) + class_id(4) + pad(4) + slots(8) + dynamic_attrs(8)
    _FPYVAL_SIZE = 16    # sizeof(FpyValue) on x64
    _FPYVAL_DATA_OFF = 8 # offsetof(FpyValue, data) = 4 (tag) + 4 (pad)

    def _emit_slot_addr_direct(self, obj: ir.Value, slot_idx: int
                                ) -> tuple[ir.Value, ir.Value]:
        """Compute (&slot.tag, &slot.data) without issuing loads. Shared by
        both read and write paths. The slots-pointer load is marked
        !invariant.load — the obj->slots pointer is set once in obj_new
        and never changes, so LLVM can CSE this load across multiple
        attribute accesses on the same object (e.g., inside a loop)."""
        obj_typed = self.builder.bitcast(obj, fpy_obj_ptr)
        slots_pp = self.builder.gep(
            obj_typed,
            [ir.Constant(i32, 0), ir.Constant(i32, 5)],  # index 5: slots (after refcount+pad, gc_node[3], magic+class_id)
            inbounds=True)
        slots_ptr = self.builder.load(slots_pp)
        if not hasattr(self, "_invariant_md"):
            self._invariant_md = self.module.add_metadata([])
        slots_ptr.set_metadata("invariant.load", self._invariant_md)
        slot_addr = self.builder.gep(
            slots_ptr, [ir.Constant(i64, slot_idx)], inbounds=True)
        tag_addr = self.builder.gep(
            slot_addr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True)
        data_addr = self.builder.gep(
            slot_addr,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True)
        return tag_addr, data_addr

    def _emit_slot_get_direct(self, obj: ir.Value, slot_idx: int
                               ) -> tuple[ir.Value, ir.Value]:
        """Emit direct IR to load obj->slots[slot_idx], returning (tag, data).

        Skips the fastpy_obj_get_slot function-call overhead. Uses GEP into
        the FpyObj struct (data layout set at module level matches MSVC x64,
        so struct offsets match C's).
        """
        tag_addr, data_addr = self._emit_slot_addr_direct(obj, slot_idx)
        tag = self.builder.load(tag_addr)
        data = self.builder.load(data_addr)
        return tag, data

    def _emit_slot_get_data_only(self, obj: ir.Value, slot_idx: int
                                  ) -> ir.Value:
        """Load only obj->slots[slot_idx].data (i64) — skips the tag load
        for statically-typed slot accesses (where the caller doesn't need
        the runtime tag). Shaves one memory load and its dead-load hazards
        off the hot path. (Phase 9 optimization: type-specialized slot reads.)
        """
        _, data_addr = self._emit_slot_addr_direct(obj, slot_idx)
        return self.builder.load(data_addr)

    def _emit_slot_set_direct(self, obj: ir.Value, slot_idx: int,
                               tag: ir.Value, data: ir.Value) -> None:
        """Emit direct IR to store (tag, data) into obj->slots[slot_idx].

        Skips the fastpy_obj_set_slot function-call overhead.
        """
        obj_typed = self.builder.bitcast(obj, fpy_obj_ptr)
        slots_pp = self.builder.gep(
            obj_typed,
            [ir.Constant(i32, 0), ir.Constant(i32, 5)],  # index 5: slots (after refcount+pad, gc_node[3], magic+class_id)
            inbounds=True)
        slots_ptr = self.builder.load(slots_pp)
        slot_addr = self.builder.gep(
            slots_ptr, [ir.Constant(i64, slot_idx)], inbounds=True)
        tag_addr = self.builder.gep(
            slot_addr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True)
        data_addr = self.builder.gep(
            slot_addr,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True)
        self.builder.store(tag, tag_addr)
        self.builder.store(data, data_addr)

    def _emit_attr_store(self, target: ast.Attribute, value: ir.Value, node: ast.AST,
                          value_node: ast.expr | None = None) -> None:
        """Emit self.x = value or obj.attr = value.

        Uses the FV-ABI obj_set_fv, which stores the value with its exact tag.
        This eliminates the old obj_set_int pointer-heuristic (Hack 2).
        The `value_node` is optional — when provided, it disambiguates pointer
        values between STR/LIST/DICT/OBJ tags.
        """
        # Class-level variable store: ClassName.attr = value → store to global
        if (isinstance(target.value, ast.Name)
                and target.value.id in self._user_classes):
            class_name = target.value.id
            key = (class_name, target.attr)
            if key in getattr(self, "_class_var_globals", {}):
                gvar, tag = self._class_var_globals[key]
                gtype = gvar.type.pointee
                # Coerce value to the global's type
                if value.type != gtype:
                    if isinstance(gtype, ir.IntType) and isinstance(value.type, ir.IntType):
                        if gtype.width > value.type.width:
                            value = self.builder.zext(value, gtype)
                        else:
                            value = self.builder.trunc(value, gtype)
                    elif isinstance(gtype, ir.DoubleType) and isinstance(value.type, ir.IntType):
                        value = self.builder.sitofp(value, gtype)
                    elif isinstance(gtype, ir.IntType) and isinstance(value.type, ir.DoubleType):
                        value = self.builder.fptosi(value, gtype)
                    elif isinstance(gtype, ir.PointerType) and isinstance(value.type, ir.IntType):
                        value = self.builder.inttoptr(value, gtype)
                self.builder.store(value, gvar)
                return

        # @property setter dispatch: obj.prop = val → call prop__set(self, val)
        obj_cls = self._infer_object_class(target.value)
        if obj_cls:
            cls_info = self._user_classes.get(obj_cls)
            if cls_info and cls_info.properties and target.attr in cls_info.properties:
                setter_name = f"{target.attr}__set"
                setter_func = cls_info.methods.get(setter_name)
                if setter_func:
                    obj = self._emit_expr_value(target.value)
                    if isinstance(obj.type, ir.IntType):
                        obj = self.builder.inttoptr(obj, i8_ptr)
                    # Coerce value to match setter param type
                    if isinstance(value.type, ir.PointerType):
                        val_i64 = self.builder.ptrtoint(value, i64)
                    elif isinstance(value.type, ir.IntType) and value.type.width != 64:
                        val_i64 = self.builder.zext(value, i64)
                    elif isinstance(value.type, ir.DoubleType):
                        val_i64 = self.builder.bitcast(value, i64)
                    else:
                        val_i64 = value
                    args = [obj, val_i64]
                    coerced = []
                    for a, p in zip(args, setter_func.args):
                        if a.type != p.type:
                            if isinstance(p.type, ir.IntType) and isinstance(a.type, ir.PointerType):
                                a = self.builder.ptrtoint(a, p.type)
                            elif isinstance(p.type, ir.PointerType) and isinstance(a.type, ir.IntType):
                                a = self.builder.inttoptr(a, p.type)
                        coerced.append(a)
                    self.builder.call(setter_func, coerced)
                    return

        obj = self._emit_expr_value(target.value)
        if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
            obj = self.builder.inttoptr(obj, i8_ptr, name="obj.ptr")
        attr_name = self._make_string_constant(target.attr)

        # Runtime-tag-preserving fast path: when the RHS is a Name variable
        # whose static tag is "none" or "obj" (these are the tags that
        # matter for sentinel-terminated structures like linked lists),
        # load the FV directly and store both tag and data to the slot.
        # This avoids stamping a static tag that's wrong at some
        # iterations (e.g., `head` may be None in iter 1 but an obj in
        # iter 2 of a loop — we can't statically know).
        if (self._USE_FV_LOCALS
                and isinstance(value_node, ast.Name)
                and value_node.id in self.variables):
            alloca_var, var_tag = self.variables[value_node.id]
            if (var_tag in ("obj", "none")
                    and isinstance(alloca_var.type, ir.PointerType)
                    and alloca_var.type.pointee is fpy_val):
                slot_idx = self._get_attr_slot(target)
                if slot_idx is not None:
                    fv = self.builder.load(alloca_var, name=f"{value_node.id}.fv")
                    tag_val = self.builder.extract_value(fv, 0)
                    data_val = self.builder.extract_value(fv, 1)
                    self._emit_slot_set_direct(
                        obj, slot_idx, tag_val, data_val)
                    return

        # Consult the local variable's static tag when the RHS is a Name.
        # This lets us disambiguate e.g. a string param stored as i64 (as
        # happens in non-FV-ABI methods during the migration).
        rhs_local_tag = None
        if isinstance(value_node, ast.Name) and value_node.id in self.variables:
            _, rhs_local_tag = self.variables[value_node.id]

        # Determine tag based on LLVM type and optional AST context
        if isinstance(value.type, ir.IntType):
            if value.type.width == 32:
                tag = FPY_TAG_BOOL
                data = self.builder.zext(value, i64)
            elif (value_node is not None
                  and isinstance(value_node, ast.Constant)
                  and value_node.value is None):
                # `self.attr = None` — preserve NONE tag so later `is None`
                # checks and sentinel-terminated traversal (e.g. linked
                # list `while cur: cur = cur.next`) work correctly.
                tag = FPY_TAG_NONE
                data = value
            elif (value_node is not None
                  and isinstance(value_node, ast.Constant)
                  and isinstance(value_node.value, bool)):
                # Bool constants are emitted as i64; preserve BOOL tag.
                tag = FPY_TAG_BOOL
                data = value
            elif (value_node is not None
                  and isinstance(value_node, ast.Name)
                  and value_node.id in self.variables
                  and self.variables[value_node.id][1] == "bool"):
                tag = FPY_TAG_BOOL
                data = value
            elif (value_node is not None
                  and (isinstance(value_node, ast.Compare)
                       or self._is_bool_typed(value_node))):
                tag = FPY_TAG_BOOL
                data = value
            elif rhs_local_tag == "bool":
                tag = FPY_TAG_BOOL
                data = value
            elif rhs_local_tag == "str":
                tag = FPY_TAG_STR
                data = value
            elif rhs_local_tag and rhs_local_tag.startswith("list"):
                tag = FPY_TAG_LIST
                data = value
            elif rhs_local_tag == "dict":
                tag = FPY_TAG_LIST
                data = value
            elif rhs_local_tag == "obj":
                tag = FPY_TAG_OBJ
                data = value
            elif rhs_local_tag == "none":
                # RHS variable currently holds None — preserve NONE tag so
                # sentinel checks (like `while x is not None:`) work.
                tag = FPY_TAG_NONE
                data = value
            else:
                tag = FPY_TAG_INT
                data = value
        elif isinstance(value.type, ir.DoubleType):
            tag = FPY_TAG_FLOAT
            data = self.builder.bitcast(value, i64)
        elif isinstance(value.type, ir.PointerType):
            # Disambiguate pointer type using AST context
            if value_node is not None:
                if self._is_list_expr(value_node) or self._is_tuple_expr(value_node):
                    tag = FPY_TAG_LIST
                elif self._is_dict_expr(value_node):
                    tag = FPY_TAG_LIST  # dicts stored as list pointers (tag reused)
                elif self._is_obj_expr(value_node):
                    tag = FPY_TAG_OBJ
                else:
                    tag = FPY_TAG_STR
            else:
                tag = FPY_TAG_STR
            data = self.builder.ptrtoint(value, i64)
        else:
            raise CodeGenError(f"Cannot set attribute with type {value.type}", node)
        # Try static slot fast path first (direct pointer-arithmetic store).
        slot_idx = self._get_attr_slot(target)
        if slot_idx is not None:
            self._emit_slot_set_direct(
                obj, slot_idx, ir.Constant(i32, tag), data)
        else:
            self.builder.call(self.runtime["obj_set_fv"],
                              [obj, attr_name, ir.Constant(i32, tag), data])

    def _infer_type_tag(self, node: ast.expr, value: ir.Value) -> str:
        """Infer the Python type tag from an AST node and LLVM value."""
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "none"
            if isinstance(node.value, bool):
                return "bool"
        # Compare / not / isinstance / bool() produce booleans
        if isinstance(node, ast.Compare):
            return "bool"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return "bool"
        # BoolOp (and/or) with all bool-typed operands → bool result; with
        # mixed types, the result is the left/right operand's type (we
        # conservatively return "int" for mixed since Python would too).
        if isinstance(node, ast.BoolOp):
            if all(self._is_bool_typed(v) for v in node.values):
                return "bool"
        # Attribute access returning an object (e.g. `node.next` where
        # `next` is a Node-typed attr). Must come before the generic
        # fall-through so the target gets an "obj" tag instead of "str".
        if isinstance(node, ast.Attribute):
            if self._is_obj_expr(node):
                return "obj"
        # Name: propagate the variable's stored tag so `cur = head` keeps
        # obj/bool/float/list/dict/tuple/str tagging instead of falling
        # through to llvm-type-based guess.
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, var_tag = self.variables[node.id]
            if var_tag in ("obj", "bool", "float", "str", "dict", "tuple",
                            "none"):
                return var_tag
            if var_tag.startswith("list"):
                return var_tag
            if var_tag.startswith("dict:"):
                return "dict"
        if isinstance(node, (ast.List, ast.ListComp, ast.GeneratorExp)):
            elem_type = self._infer_list_elem_type(node)
            return f"list:{elem_type}"
        if isinstance(node, ast.Tuple):
            return "tuple"
        # divmod returns a tuple
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "divmod":
                return "tuple"
            if node.func.id == "dict":
                return "dict"
            if node.func.id == "tuple":
                return "tuple"
            if node.func.id == "set":
                return "set"
            if node.func.id in ("list", "sorted", "reversed"):
                return "list:int"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in self._user_classes:
                return "obj"
            # Check if the called function contains closures (returns a closure)
            for full_name in self._closure_info:
                if full_name.startswith(f"{node.func.id}."):
                    return "closure"
            # Check if function returns a pointer (tuple, list, or dict)
            if node.func.id in self._user_functions:
                info = self._user_functions[node.func.id]
                if info.ret_tag == "dict":
                    return "dict"
                if info.ret_tag == "ptr:list":
                    return "list:list"  # function returns list of lists
                if info.ret_tag == "ptr":
                    return "list:int"  # default to list for pointer returns
                if info.ret_tag == "obj":
                    return "obj"
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return "dict"
        # dict | dict → dict
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
                and self._is_dict_expr(node.left) and self._is_dict_expr(node.right)):
            return "dict"
        # Method calls that return lists
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if method == "split":
                return "list:str"
            if method in ("keys", "values", "items"):
                return "list:str"
            if method == "copy" and self._is_list_expr(node.func.value):
                return "list:int"
            # User class method return: check method return type
            ret_type = self._find_method_return_type(node.func.value, method)
            if ret_type is not None and isinstance(ret_type, ir.PointerType):
                if self._method_returns_list(node.func.value, method):
                    return "list:int"
                if self._method_returns_dict(node.func.value, method):
                    return "dict"
                if self._method_returns_tuple(node.func.value, method):
                    return "tuple"
                # Return self or cls(...) — returns an obj
                if self._infer_object_class(node) is not None:
                    return "obj"
        # Builtin calls that return lists
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("sorted", "reversed", "list"):
                # Inherit elem type from argument
                if node.args:
                    if self._is_list_expr(node.args[0]):
                        elem = self._get_list_elem_type(node.args[0])
                        return f"list:{elem}"
                return "list:int"
        # Dict subscript: infer value type from known dict-value-type sets
        if (isinstance(node, ast.Subscript)
                and not isinstance(node.slice, ast.Slice)
                and isinstance(node.value, ast.Name)
                and self._is_dict_expr(node.value)):
            name = node.value.id
            if name in self._dict_var_list_values:
                return "list:int"
            if name in self._dict_var_dict_values:
                return "dict"
            if name in self._dict_var_int_values:
                return "int"
        # Slice on a list/tuple: returns a list (inherit elem type)
        if (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Slice)
                and (self._is_list_expr(node.value)
                     or self._is_tuple_expr(node.value))):
            elem = self._get_list_elem_type(node.value)
            return f"list:{elem}"
        # BinOp on objects (operator overloading) returns an object
        if isinstance(node, ast.BinOp):
            if self._is_obj_expr(node.left):
                return "obj"
            # List concat / repeat / set ops yield lists
            if (self._is_list_expr(node.left) or self._is_list_expr(node.right)
                    or self._is_tuple_expr(node.left) or self._is_tuple_expr(node.right)):
                # Inherit element type from a list operand if known
                for operand in (node.left, node.right):
                    if self._is_list_expr(operand):
                        elem = self._get_list_elem_type(operand)
                        return f"list:{elem}"
                return "list:int"
        if isinstance(node, (ast.Set, ast.SetComp)):
            return "set"
        return self._llvm_type_tag(value)

    def _prescan_list_append_types(self, stmts: list[ast.stmt],
                                    known_types: dict[str, str] | None = None
                                    ) -> None:
        """Pre-scan statements to infer list element types from append() calls.

        When a variable is assigned an empty list (x = []) and later has
        .append() called with a recognizable type (list, str, obj), record
        that so the type tag can be set correctly at assignment time.

        `known_types` optionally provides types for names that aren't local
        assignments (e.g. function parameters whose types came from
        call-site analysis). Used to resolve `for c in s:` where `s` is a
        parameter.
        """
        if known_types is None:
            known_types = {}
        # Pre-scan: detect dict value types from `d[k] = <int_const>` etc.
        # This lets `d = {}` be tracked as dict:int if any later assignment
        # stores an int value, which in turn makes `d[k]` return an int and
        # avoids type-mismatch errors on `d[k] + 1`-style patterns.
        _empty_dict_vars: set[str] = set()
        for stmt in stmts:
            for n in ast.walk(stmt):
                if (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name)
                        and isinstance(n.value, ast.Dict)
                        and not n.value.keys):
                    _empty_dict_vars.add(n.targets[0].id)
        if _empty_dict_vars:
            for stmt in stmts:
                for n in ast.walk(stmt):
                    if (isinstance(n, ast.Assign) and len(n.targets) == 1
                            and isinstance(n.targets[0], ast.Subscript)
                            and isinstance(n.targets[0].value, ast.Name)
                            and n.targets[0].value.id in _empty_dict_vars):
                        base = n.targets[0].value.id
                        v = n.value
                        if isinstance(v, (ast.Dict, ast.DictComp)):
                            self._dict_var_dict_values.add(base)
                        elif isinstance(v, (ast.List, ast.ListComp)):
                            self._dict_var_list_values.add(base)
                        elif (isinstance(v, ast.Constant)
                              and isinstance(v.value, int)
                              and not isinstance(v.value, bool)):
                            self._dict_var_int_values.add(base)
                        elif (isinstance(v, ast.Call)
                              and isinstance(v.func, ast.Name)
                              and v.func.id in self._user_classes):
                            # d[k] = ClassName(...)
                            self._dict_var_obj_values.add(base)
                        elif isinstance(v, ast.BinOp):
                            # d[k] = d[k] + 1 pattern — assume int.
                            # Check that the RHS is an int-flavored op.
                            is_int = True
                            for sub in ast.walk(v):
                                if (isinstance(sub, ast.Constant)
                                        and isinstance(sub.value, float)):
                                    is_int = False
                                    break
                            if is_int:
                                self._dict_var_int_values.add(base)
        # Find variables assigned empty lists (anywhere in the scope, including nested blocks)
        empty_list_vars: set[str] = set()
        # Also track variables assigned list literals (for recognizing list variables)
        list_vars: set[str] = set()
        # Track loop-variable types for `for c in <typed iter>:`. Used to
        # infer .append(c) element types when c comes from iterating a
        # known-typed iterable (e.g. a string).
        loop_var_types: dict[str, str] = {}
        local_var_types: dict[str, str] = {}
        for stmt in stmts:
            for node in ast.walk(stmt):
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)):
                    tgt = node.targets[0].id
                    if isinstance(node.value, ast.List):
                        list_vars.add(tgt)
                        if not node.value.elts:
                            empty_list_vars.add(tgt)
                    elif isinstance(node.value, ast.ListComp):
                        list_vars.add(tgt)
                    elif (isinstance(node.value, ast.Constant)
                          and isinstance(node.value.value, str)):
                        local_var_types[tgt] = "str"
                    elif isinstance(node.value, ast.JoinedStr):
                        local_var_types[tgt] = "str"
                if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                    name = node.target.id
                    it = node.iter
                    # for c in "string" / for c in some_str → c is str
                    if (isinstance(it, ast.Constant)
                            and isinstance(it.value, str)):
                        loop_var_types[name] = "str"
                    elif (isinstance(it, ast.Name)
                          and it.id in local_var_types
                          and local_var_types[it.id] == "str"):
                        loop_var_types[name] = "str"
                    elif (isinstance(it, ast.Name)
                          and it.id in known_types
                          and known_types[it.id] == "str"):
                        # for c in <str param>
                        loop_var_types[name] = "str"
                    # for c in a_list_of_str
                    elif (isinstance(it, ast.Name)
                          and it.id in self._list_append_types
                          and self._list_append_types[it.id] == "str"):
                        loop_var_types[name] = "str"

        if not empty_list_vars:
            return

        # Walk all statements (including nested in loops/if) looking for .append() calls
        for stmt in stmts:
            for node in ast.walk(stmt):
                if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
                    continue
                call = node.value
                if not (isinstance(call.func, ast.Attribute)
                        and call.func.attr == "append"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id in empty_list_vars
                        and len(call.args) == 1):
                    continue
                var_name = call.func.value.id
                arg = call.args[0]
                # Infer what type is being appended
                if isinstance(arg, (ast.List, ast.ListComp)):
                    self._list_append_types[var_name] = "list"
                elif isinstance(arg, ast.Tuple):
                    # Appending a tuple literal — tuple elements
                    self._list_append_types[var_name] = "tuple"
                elif isinstance(arg, (ast.Dict, ast.DictComp)):
                    # Appending a dict literal — dict elements
                    self._list_append_types[var_name] = "dict"
                elif isinstance(arg, ast.Name) and (arg.id in self._list_append_types or arg.id in list_vars):
                    # Appending a variable that is a list
                    self._list_append_types[var_name] = "list"
                elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                    if arg.func.id in self._user_classes:
                        self._list_append_types[var_name] = "obj"
                elif isinstance(arg, ast.Constant):
                    # String/float/bool constants propagate to element type
                    if isinstance(arg.value, str):
                        self._list_append_types[var_name] = "str"
                    elif isinstance(arg.value, float):
                        self._list_append_types[var_name] = "float"
                elif isinstance(arg, ast.JoinedStr):
                    self._list_append_types[var_name] = "str"
                elif isinstance(arg, ast.Name):
                    # Appending a known-typed variable (loop var from str
                    # iteration, previously-assigned str var, etc.).
                    if arg.id in loop_var_types:
                        self._list_append_types[var_name] = loop_var_types[arg.id]
                    elif arg.id in local_var_types:
                        self._list_append_types[var_name] = local_var_types[arg.id]
                    elif arg.id in self.variables:
                        _, tag = self.variables[arg.id]
                        if tag == "str":
                            self._list_append_types[var_name] = "str"
                        elif tag == "float":
                            self._list_append_types[var_name] = "float"

    def _infer_list_elem_type(self, node: ast.expr) -> str:
        """Infer the element type of a list expression."""
        if isinstance(node, ast.List):
            if not node.elts:
                return "int"
            first = node.elts[0]
            if isinstance(first, ast.Constant):
                if isinstance(first.value, str):
                    return "str"
                elif isinstance(first.value, float):
                    return "float"
            # Check if elements are nested lists or tuples (both stored as list pointers)
            if isinstance(first, (ast.List, ast.ListComp, ast.Tuple)):
                return "list"
            # Check if elements are dicts
            if isinstance(first, (ast.Dict, ast.DictComp)):
                return "dict"
            # Check if elements are constructor calls (list of objects)
            if isinstance(first, ast.Call) and isinstance(first.func, ast.Name):
                if first.func.id in self._user_classes:
                    return "obj"
            # BinOp with a list/tuple operand: [[0]*n, ...] or [lst+lst, ...]
            if isinstance(first, ast.BinOp):
                if (isinstance(first.left, (ast.List, ast.ListComp, ast.Tuple))
                        or isinstance(first.right, (ast.List, ast.ListComp, ast.Tuple))):
                    return "list"
            return "int"
        if isinstance(node, ast.ListComp):
            # Infer from the element expression
            elt = node.elt
            if isinstance(elt, (ast.List, ast.ListComp, ast.Tuple)):
                return "list"
            if isinstance(elt, (ast.Dict, ast.DictComp)):
                return "dict"
            if isinstance(elt, ast.Constant):
                if isinstance(elt.value, str):
                    return "str"
                if isinstance(elt.value, float):
                    return "float"
            if isinstance(elt, ast.JoinedStr):
                return "str"
            # BinOp with a list/tuple operand: [x]*n or lst+lst
            if isinstance(elt, ast.BinOp):
                if (isinstance(elt.left, (ast.List, ast.ListComp, ast.Tuple))
                        or isinstance(elt.right, (ast.List, ast.ListComp, ast.Tuple))):
                    return "list"
            # Element is the outermost generator's loop variable:
            # `[p for p in people]` — inherit the iterable's element type.
            # Lets `[p for p in list_of_dicts]` be tagged list:dict.
            if (isinstance(elt, ast.Name) and node.generators
                    and isinstance(node.generators[0].target, ast.Name)
                    and node.generators[0].target.id == elt.id):
                return self._get_list_elem_type(node.generators[0].iter)
            return "int"
        return "int"

    def _emit_tuple_unpack(self, target: ast.Tuple, value_node: ast.expr, node: ast.AST) -> None:
        """Emit tuple unpacking: a, b, c = 1, 2, 3 or a, b, c = some_tuple."""
        if isinstance(value_node, ast.Tuple):
            # Direct unpacking: a, b, c = 1, 2, 3
            # Evaluate ALL values first, then assign (Python semantics)
            if len(target.elts) != len(value_node.elts):
                raise CodeGenError(
                    f"Cannot unpack {len(value_node.elts)} values into {len(target.elts)} targets",
                    node,
                )
            values = []
            for val in value_node.elts:
                v = self._emit_expr_value(val)
                tag = self._infer_type_tag(val, v)
                values.append((v, tag))
            for tgt, (v, tag) in zip(target.elts, values):
                if isinstance(tgt, ast.Name):
                    self._store_variable(tgt.id, v, tag)
                elif isinstance(tgt, ast.Subscript):
                    self._emit_subscript_store(tgt, v, node)
                elif isinstance(tgt, ast.Attribute):
                    self._emit_attr_store(tgt, v, node)
                else:
                    raise CodeGenError("Unsupported unpack target", node)
        elif self._is_list_expr(value_node) or self._is_tuple_expr(value_node) or isinstance(value_node, ast.List):
            # Unpacking from a list/tuple variable
            val = self._emit_expr_value(value_node)
            # Check for starred target
            star_idx = None
            for i, tgt in enumerate(target.elts):
                if isinstance(tgt, ast.Starred):
                    star_idx = i
                    break

            if star_idx is not None:
                # Starred unpacking: first, *rest = list or *init, last = list
                list_len = self.builder.call(self.runtime["list_length"], [val])
                n_fixed = len(target.elts) - 1  # everything except the starred

                for i, tgt in enumerate(target.elts):
                    if isinstance(tgt, ast.Starred):
                        # *rest gets a slice
                        name = tgt.value.id if isinstance(tgt.value, ast.Name) else None
                        if name is None:
                            raise CodeGenError("Starred unpack target must be a name", node)
                        start = ir.Constant(i64, star_idx)
                        # stop = list_len - (n_targets_after_star)
                        n_after = len(target.elts) - star_idx - 1
                        stop = self.builder.sub(list_len, ir.Constant(i64, n_after))
                        rest = self.builder.call(self.runtime["list_slice"], [
                            val, start, stop, ir.Constant(i64, 1), ir.Constant(i64, 1)])
                        self._store_variable(name, rest, "list:int")
                    elif isinstance(tgt, ast.Name):
                        if i < star_idx:
                            idx = ir.Constant(i64, i)
                        else:
                            # After the star: index from end
                            offset = len(target.elts) - i
                            idx = self.builder.sub(list_len, ir.Constant(i64, offset))
                        elem = self._list_get_as_bare(val, idx, "int")
                        self._store_variable(tgt.id, elem, "int")
                    else:
                        raise CodeGenError("Unsupported unpack target", node)
            else:
                # Simple unpacking: a, b, c = list
                for i, tgt in enumerate(target.elts):
                    if isinstance(tgt, ast.Name):
                        elem = self._list_get_as_bare(val, ir.Constant(i64, i), "int")
                        self._store_variable(tgt.id, elem, "int")
                    else:
                        raise CodeGenError("Unsupported unpack target", node)
        else:
            raise CodeGenError("Tuple unpacking from non-tuple not yet supported", node)

    def _emit_aug_assign(self, node: ast.AugAssign) -> None:
        """Emit augmented assignment: x += expr, x -= expr, etc."""
        if isinstance(node.target, ast.Attribute):
            # self.n += 1 => self.n = self.n + 1
            current = self._emit_attr_load(node.target)
            rhs = self._emit_expr_value(node.value)
            if isinstance(current.type, ir.DoubleType) or isinstance(rhs.type, ir.DoubleType):
                if isinstance(current.type, ir.IntType):
                    current = self.builder.sitofp(current, double)
                if isinstance(rhs.type, ir.IntType):
                    rhs = self.builder.sitofp(rhs, double)
                result = self._emit_float_binop(node.op, current, rhs, node)
            else:
                result = self._emit_int_binop(node.op, current, rhs, node)
            self._emit_attr_store(node.target, result, node)
            return

        if isinstance(node.target, ast.Subscript):
            # d[k] += v / lst[i] += v — load FV, op, store via FV-ABI.
            # We use the raw FV (rather than _emit_subscript's typed unwrap)
            # so the rhs type can drive the correct interpretation when the
            # dict's static value type is unknown (counts[w] += 1 pattern).
            rhs = self._emit_expr_value(node.value)
            fv = self._load_or_wrap_fv(node.target)
            data = self._fv_data_i64(fv)
            if isinstance(rhs.type, ir.DoubleType):
                current = self.builder.bitcast(data, double)
                result = self._emit_float_binop(node.op, current, rhs, node)
            elif isinstance(rhs.type, ir.IntType):
                current = data
                if rhs.type.width != 64:
                    rhs = self.builder.zext(rhs, i64) if rhs.type.width < 64 else self.builder.trunc(rhs, i64)
                result = self._emit_int_binop(node.op, current, rhs, node)
            elif isinstance(rhs.type, ir.PointerType) and isinstance(node.op, ast.Add):
                # String concatenation
                current_ptr = self.builder.inttoptr(data, i8_ptr)
                result = self.builder.call(self.runtime["str_concat"], [current_ptr, rhs])
            else:
                # Fall back to the original typed-subscript path
                current = self._emit_subscript(node.target)
                result = self._emit_int_binop(node.op, current, rhs, node)
            self._emit_subscript_store(node.target, result, node)
            return

        if not isinstance(node.target, ast.Name):
            raise CodeGenError(
                f"Unsupported augmented assignment target: {type(node.target).__name__}",
                node,
            )

        # Load current value
        current = self._load_variable(node.target.id, node)

        # Evaluate RHS
        rhs = self._emit_expr_value(node.value)

        # Pointer types: list/string concatenation
        if isinstance(current.type, ir.PointerType) and isinstance(node.op, ast.Add):
            # Check if it's a list
            target_name = node.target.id
            _, tag = self.variables.get(target_name, (None, ""))
            if tag.startswith("list") or self._is_list_expr(ast.Name(id=target_name)):
                result = self.builder.call(self.runtime["list_concat"], [current, rhs])
                self._store_variable(target_name, result, tag or "list:int")
                return
            # String concatenation
            if isinstance(rhs.type, ir.PointerType):
                result = self.builder.call(self.runtime["str_concat"], [current, rhs])
                self._store_variable(target_name, result, "str")
                return

        # List repetition: lst *= n
        if isinstance(current.type, ir.PointerType) and isinstance(node.op, ast.Mult):
            target_name = node.target.id
            _, tag = self.variables.get(target_name, (None, ""))
            if tag.startswith("list"):
                result = self.builder.call(self.runtime["list_repeat"], [current, rhs])
                self._store_variable(target_name, result, tag)
                return

        # Type promotion
        if isinstance(current.type, ir.DoubleType) or isinstance(rhs.type, ir.DoubleType):
            if isinstance(current.type, ir.IntType):
                current = self.builder.sitofp(current, double)
            if isinstance(rhs.type, ir.IntType):
                rhs = self.builder.sitofp(rhs, double)
            result = self._emit_float_binop(node.op, current, rhs, node)
        else:
            result = self._emit_int_binop(node.op, current, rhs, node)

        type_tag = self._llvm_type_tag(result)
        self._store_variable(node.target.id, result, type_tag)

    def _create_entry_alloca(self, llvm_type: ir.Type, name: str) -> ir.AllocaInstr:
        """Create an alloca in the function's entry block (standard LLVM pattern)."""
        entry_block = self.function.entry_basic_block
        # Save current position, insert at start of entry block
        saved_block = self.builder.block
        if entry_block.instructions:
            self.builder.position_before(entry_block.instructions[0])
        else:
            self.builder.position_at_end(entry_block)
        alloca = self.builder.alloca(llvm_type, name=name)
        # Restore position
        self.builder.position_at_end(saved_block)
        return alloca

    # Flip this to True to store locals as FpyValue. Globals and closure
    # cells keep their old representation (globals as i64, cells as heap-
    # allocated FpyCell). During the gradual migration, setting this to
    # False restores the previous bare-type allocas exactly.
    _USE_FV_LOCALS = True

    def _store_variable(self, name: str, value: ir.Value, type_tag: str) -> None:
        """Store a value in a variable, creating the alloca if needed.

        With _USE_FV_LOCALS=True: locals are `%fpyvalue` allocas. We wrap
        the incoming bare value into FpyValue using `type_tag`, then store.
        Globals remain as i64 globals; cells remain as heap FpyCell.
        """
        # Globals (declared at module scope or via `global x` in a function):
        # stored as i64 directly into the LLVM global, same as before.
        if name in self._global_vars:
            gvar, _ = self._global_vars[name]
            gvar_type = gvar.type.pointee  # the type the global holds
            if gvar_type == i8_ptr:
                # Pointer global (list, dict, str)
                if isinstance(value.type, ir.IntType):
                    value = self.builder.inttoptr(value, i8_ptr)
                elif isinstance(value.type, ir.LiteralStructType):
                    # FpyValue — extract data and convert to pointer
                    data = self.builder.extract_value(value, 1)
                    value = self.builder.inttoptr(data, i8_ptr)
            elif gvar_type == double:
                # Float global
                if isinstance(value.type, ir.IntType):
                    value = self.builder.bitcast(value, double)
            else:
                # i64 global (default)
                if isinstance(value.type, ir.PointerType):
                    value = self.builder.ptrtoint(value, i64)
                elif isinstance(value.type, ir.DoubleType):
                    value = self.builder.bitcast(value, i64)
                elif isinstance(value.type, ir.IntType) and value.type.width != 64:
                    value = self.builder.zext(value, i64)
                elif isinstance(value.type, ir.LiteralStructType):
                    value = self.builder.extract_value(value, 1)
            self.builder.store(value, gvar)
            self.variables[name] = (gvar, type_tag)
            return

        # Closure cell: unchanged — stored via cell_set
        if name in self.variables:
            alloca, old_tag = self.variables[name]
            if old_tag == "cell":
                cell_ptr = self.builder.load(alloca)
                self.builder.call(self.runtime["cell_set"], [cell_ptr, value])
                return

        if not self._USE_FV_LOCALS:
            # Legacy path: bare-type alloca
            if name in self.variables:
                alloca, _ = self.variables[name]
                if value.type != alloca.type.pointee:
                    alloca = self._create_entry_alloca(value.type, name)
                    self.variables[name] = (alloca, type_tag)
            else:
                alloca = self._create_entry_alloca(value.type, name)
                self.variables[name] = (alloca, type_tag)
            self.builder.store(value, alloca)
            return

        # FV path: alloca is always %fpyvalue; wrap bare value into FpyValue
        # If the value is already an FpyValue (e.g., from a direct FV-ABI call
        # result), store it directly to preserve the runtime tag.
        if (isinstance(value.type, ir.LiteralStructType)
                and value.type == fpy_val):
            fv = value
        else:
            fv = self._wrap_bare_to_fv(value, type_tag)
        if name in self.variables:
            alloca, old_tag = self.variables[name]
            # If the existing alloca is not fpy_val (e.g., a cell or a
            # pre-existing bare alloca), create a new one.
            if not (isinstance(alloca.type, ir.PointerType)
                    and alloca.type.pointee is fpy_val):
                alloca = self._create_entry_alloca(fpy_val, name)
            elif self._USE_REFCOUNT:
                # Decref the old value being overwritten
                # DISABLED: causes __lt__ corruption — needs investigation
                old_fv = self.builder.load(alloca, name=f"{name}.old")
                old_tag_val = self.builder.extract_value(old_fv, 0)
                old_data = self.builder.extract_value(old_fv, 1)
                self.builder.call(self.runtime["rc_decref"],
                                  [old_tag_val, old_data])
        else:
            alloca = self._create_entry_alloca(fpy_val, name)
            # Zero-initialize new allocas so first decref is safe
            if self._USE_REFCOUNT:
                self.builder.store(self._fv_none(), alloca)
        # Incref the new value being stored
        if self._USE_REFCOUNT:
            new_tag = self.builder.extract_value(fv, 0)
            new_data = self.builder.extract_value(fv, 1)
            self.builder.call(self.runtime["rc_incref"],
                              [new_tag, new_data])
        self.variables[name] = (alloca, type_tag)
        self.builder.store(fv, alloca)

    def _load_variable(self, name: str, node: ast.AST) -> ir.Value:
        """Load a variable's value. Returns a bare LLVM value (not FpyValue)
        of the type dictated by the variable's current type_tag."""
        if name not in self.variables:
            raise CodeGenError(f"Undefined variable: {name}", node)
        alloca, type_tag = self.variables[name]
        if type_tag == "cell":
            # Mutable closure variable — load cell pointer, then get value
            cell_ptr = self.builder.load(alloca, name=f"{name}.cell")
            return self.builder.call(self.runtime["cell_get"], [cell_ptr])

        # Globals stay as i64 (or whatever the alloca type is)
        if name in self._global_vars:
            return self.builder.load(alloca, name=name)

        if not self._USE_FV_LOCALS:
            return self.builder.load(alloca, name=name)

        # FV path: load FpyValue, unwrap to the bare type expected by callers
        # (determined by the variable's current type_tag)
        if isinstance(alloca.type, ir.PointerType) and alloca.type.pointee is fpy_val:
            fv = self.builder.load(alloca, name=f"{name}.fv")
            return self._unwrap_fv_for_tag(fv, type_tag)
        # Legacy alloca (not yet migrated) — load directly
        return self.builder.load(alloca, name=name)

    def _wrap_bare_to_fv(self, value: ir.Value, type_tag: str) -> ir.Value:
        """Wrap a bare LLVM value into an FpyValue using the static type_tag."""
        # Pointer types — need to pick the right tag
        if isinstance(value.type, ir.PointerType):
            if type_tag == "str":
                return self._fv_from_str(value)
            if type_tag == "obj":
                return self._fv_from_obj(value)
            if type_tag == "dict":
                return self._fv_from_dict(value)
            if type_tag == "set":
                tag = ir.Constant(i32, FPY_TAG_SET)
                data = self.builder.ptrtoint(value, i64)
                return self._fv_build_from_slots(tag, data)
            if type_tag == "tuple" or type_tag.startswith("list"):
                return self._fv_from_list(value)
            if type_tag == "closure":
                # Closures are pointers — treat as OBJ for now
                return self._fv_from_obj(value)
            if type_tag == "pyobj":
                # CPython PyObject* — store as OBJ tag with raw pointer
                return self._fv_from_obj(value)
            if type_tag == "none":
                return self._fv_none()
            # Default pointer → string
            return self._fv_from_str(value)
        # Integer types
        if isinstance(value.type, ir.IntType):
            if value.type.width == 32:
                # Could be bool or truncated int
                if type_tag == "bool":
                    return self._fv_from_bool(value)
                return self._fv_from_bool(value)  # i32 always = bool in our codegen
            if type_tag == "bool":
                return self._fv_from_bool(value)
            if type_tag == "none":
                return self._fv_none()
            if type_tag == "pyobj":
                # i64 holding a PyObject* pointer — wrap as OBJ
                ptr = self.builder.inttoptr(value, i8_ptr)
                return self._fv_from_obj(ptr)
            return self._fv_from_int(value)
        # Double
        if isinstance(value.type, ir.DoubleType):
            return self._fv_from_float(value)
        raise CodeGenError(f"Cannot wrap value of type {value.type} (tag={type_tag})")

    def _unwrap_fv_for_tag(self, fv: ir.Value, type_tag: str) -> ir.Value:
        """Unwrap an FpyValue into a bare LLVM value of the type indicated by type_tag."""
        if type_tag == "str":
            return self._fv_as_ptr(fv)
        if type_tag == "obj":
            return self._fv_as_ptr(fv)
        if type_tag == "dict":
            return self._fv_as_ptr(fv)
        if type_tag == "set":
            return self._fv_as_ptr(fv)
        if type_tag == "tuple" or type_tag.startswith("list"):
            return self._fv_as_ptr(fv)
        if type_tag == "closure":
            return self._fv_as_ptr(fv)
        if type_tag == "pyobj":
            return self._fv_as_ptr(fv)
        if type_tag == "float":
            return self._fv_as_float(fv)
        if type_tag == "bool":
            # Tag BOOL's data is 0/1 stored as i64; truncate to i32 for bool
            data = self._fv_as_int(fv)
            return self.builder.trunc(data, i32)
        if type_tag == "none":
            return ir.Constant(i64, 0)
        # Default: int
        return self._fv_as_int(fv)

    def _fv_store_from_list(self, name: str, list_val: ir.Value,
                             idx: ir.Value, type_tag: str) -> None:
        """Fetch an FV element from list_val[idx] and store directly into
        the variable's FV alloca. Avoids the unwrap-then-rewrap round-trip
        that happens if you call list_get_* → _store_variable.
        """
        if not self._USE_FV_LOCALS:
            # Legacy path: unwrap and go through _store_variable
            # (kept for safety if someone flips the flag off)
            tag_slot = self._create_entry_alloca(i32, "lget.tag")
            data_slot = self._create_entry_alloca(i64, "lget.data")
            self.builder.call(self.runtime["list_get_fv"],
                              [list_val, idx, tag_slot, data_slot])
            data = self.builder.load(data_slot)
            fv = self._fv_build_from_slots(
                self.builder.load(tag_slot), data)
            bare = self._unwrap_fv_for_tag(fv, type_tag)
            self._store_variable(name, bare, type_tag)
            return

        # FV path: get (tag, data) and pack directly into the alloca's FV
        tag_slot = self._create_entry_alloca(i32, "lget.tag")
        data_slot = self._create_entry_alloca(i64, "lget.data")
        self.builder.call(self.runtime["list_get_fv"],
                          [list_val, idx, tag_slot, data_slot])
        loaded_tag = self.builder.load(tag_slot)
        loaded_data = self.builder.load(data_slot)
        fv = ir.Constant(fpy_val, ir.Undefined)
        fv = self.builder.insert_value(fv, loaded_tag, 0)
        fv = self.builder.insert_value(fv, loaded_data, 1)

        # Get or create an FV alloca for the variable
        if name in self.variables:
            alloca, _ = self.variables[name]
            if not (isinstance(alloca.type, ir.PointerType)
                    and alloca.type.pointee is fpy_val):
                alloca = self._create_entry_alloca(fpy_val, name)
        else:
            alloca = self._create_entry_alloca(fpy_val, name)
        self.variables[name] = (alloca, type_tag)
        self.builder.store(fv, alloca)

    def _fv_build_from_slots(self, tag: ir.Value, data: ir.Value) -> ir.Value:
        """Build an FpyValue from (i32 tag, i64 data)."""
        fv = ir.Constant(fpy_val, ir.Undefined)
        fv = self.builder.insert_value(fv, tag, 0)
        fv = self.builder.insert_value(fv, data, 1)
        return fv

    def _fv_list_get(self, lst: ir.Value, idx: ir.Value,
                      slot_prefix: str = "lget") -> tuple[ir.Value, ir.Value]:
        """Call list_get_fv and return (tag, data) loaded from the output slots."""
        tag_slot = self._create_entry_alloca(i32, f"{slot_prefix}.tag")
        data_slot = self._create_entry_alloca(i64, f"{slot_prefix}.data")
        self.builder.call(self.runtime["list_get_fv"],
                          [lst, idx, tag_slot, data_slot])
        return self.builder.load(tag_slot), self.builder.load(data_slot)

    def _list_get_as_bare(self, lst: ir.Value, idx: ir.Value,
                           elem_type: str) -> ir.Value:
        """Get an element via list_get_fv and unwrap to the bare type
        indicated by elem_type ('int', 'str', 'list', 'dict', 'obj', 'float').
        """
        _tag, data = self._fv_list_get(lst, idx)
        if elem_type in ("str", "obj", "list", "dict"):
            return self.builder.inttoptr(data, i8_ptr)
        if elem_type == "float":
            return self.builder.bitcast(data, double)
        return data  # int (default)

    def _llvm_type_tag(self, value: ir.Value) -> str:
        """Determine the type tag for an LLVM value."""
        if isinstance(value.type, ir.IntType):
            if value.type.width == 64:
                return "int"
            elif value.type.width == 32:
                return "bool"
        elif isinstance(value.type, ir.DoubleType):
            return "float"
        elif isinstance(value.type, ir.PointerType):
            return "str"
        return "unknown"

    def _new_block(self, name: str) -> ir.Block:
        """Create a new basic block with a unique name."""
        self._block_counter += 1
        return self.function.append_basic_block(f"{name}.{self._block_counter}")

    def _emit_stmts(self, stmts: list[ast.stmt]) -> None:
        """Emit a list of statements."""
        for stmt in stmts:
            # Don't emit code after a terminator (break/continue/return)
            if self.builder.block.is_terminated:
                break
            self._emit_stmt(stmt)

    # -----------------------------------------------------------------
    # Control flow
    # -----------------------------------------------------------------

    def _emit_if(self, node: ast.If) -> None:
        """Emit if/elif/else."""
        cond = self._emit_condition(node.test)
        then_block = self._new_block("if.then")
        merge_block = self._new_block("if.end")

        if node.orelse:
            else_block = self._new_block("if.else")
            self.builder.cbranch(cond, then_block, else_block)
        else:
            self.builder.cbranch(cond, then_block, merge_block)

        # Then branch
        self.builder.position_at_end(then_block)
        self._emit_stmts(node.body)
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_block)

        # Else branch
        if node.orelse:
            self.builder.position_at_end(else_block)
            self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)

        self.builder.position_at_end(merge_block)

    def _emit_while(self, node: ast.While) -> None:
        """Emit while loop."""
        cond_block = self._new_block("while.cond")
        body_block = self._new_block("while.body")
        else_block = self._new_block("while.else") if node.orelse else None
        end_block = self._new_block("while.end")

        # Jump to condition check
        self.builder.branch(cond_block)

        # Condition check
        self.builder.position_at_end(cond_block)
        cond = self._emit_condition(node.test)
        after_loop = else_block if else_block else end_block
        self.builder.cbranch(cond, body_block, after_loop)

        # Body
        self.builder.position_at_end(body_block)
        self._loop_stack.append((end_block, cond_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Else (runs if loop completed without break)
        if else_block:
            self.builder.position_at_end(else_block)
            self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)

    def _emit_for(self, node: ast.For) -> None:
        """Emit for loop: for <var> in range(...) or for <var> in <list>."""
        # Handle tuple unpacking target: for k, v in ...
        if isinstance(node.target, ast.Tuple):
            self._emit_for_tuple_unpack(node)
            return

        if not isinstance(node.target, ast.Name):
            raise CodeGenError("Only simple variable targets in for loops", node)

        # Check for `for x in <list>` or `for x in <tuple>`. Tuples are
        # stored as lists internally, so the same iteration code works.
        if self._is_list_expr(node.iter) or self._is_tuple_expr(node.iter):
            self._emit_for_list(node)
            return

        # Also handle `for x in <literal list>` or `for x in (1, 2, 3)`
        if isinstance(node.iter, (ast.List, ast.Tuple)):
            self._emit_for_list(node)
            return

        # Check for `for ch in string`
        if isinstance(node.iter, ast.Constant) and isinstance(node.iter.value, str):
            self._emit_for_string(node)
            return
        if isinstance(node.iter, ast.Name) and node.iter.id in self.variables:
            _, tag = self.variables[node.iter.id]
            if tag == "str":
                self._emit_for_string(node)
                return
            if tag == "dict":
                # for k in d: -> iterate over d.keys()
                self._emit_for_dict(node)
                return
        if self._is_dict_expr(node.iter):
            self._emit_for_dict(node)
            return

        # Iterator protocol: for x in obj with __iter__/__next__
        if self._is_obj_expr(node.iter):
            obj_cls = self._infer_object_class(node.iter)
            if obj_cls and self._class_has_method(obj_cls, "__iter__"):
                self._emit_for_iter_protocol(node)
                return

        # Parse range() call
        if not (isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"):
            raise CodeGenError("Only 'for x in range(...)' or 'for x in list/string' is supported", node)

        range_args = node.iter.args
        if len(range_args) == 1:
            start = ir.Constant(i64, 0)
            stop = self._emit_expr_value(range_args[0])
            step = ir.Constant(i64, 1)
        elif len(range_args) == 2:
            start = self._emit_expr_value(range_args[0])
            stop = self._emit_expr_value(range_args[1])
            step = ir.Constant(i64, 1)
        elif len(range_args) == 3:
            start = self._emit_expr_value(range_args[0])
            stop = self._emit_expr_value(range_args[1])
            step = self._emit_expr_value(range_args[2])
        else:
            raise CodeGenError("range() takes 1-3 arguments", node)

        var_name = node.target.id

        # Initialize loop variable
        self._store_variable(var_name, start, "int")

        cond_block = self._new_block("for.cond")
        body_block = self._new_block("for.body")
        incr_block = self._new_block("for.incr")
        else_block = self._new_block("for.else") if node.orelse else None
        end_block = self._new_block("for.end")

        self.builder.branch(cond_block)

        # Condition: i < stop (for positive step) or i > stop (for negative)
        self.builder.position_at_end(cond_block)
        current = self._load_variable(var_name, node)
        # Check sign of step: if step > 0 use <, if step < 0 use >
        step_positive = self.builder.icmp_signed(">", step, ir.Constant(i64, 0))
        lt_cond = self.builder.icmp_signed("<", current, stop)
        gt_cond = self.builder.icmp_signed(">", current, stop)
        cond = self.builder.select(step_positive, lt_cond, gt_cond)
        after_loop = else_block if else_block else end_block
        self.builder.cbranch(cond, body_block, after_loop)

        # Body
        self.builder.position_at_end(body_block)
        self._loop_stack.append((end_block, incr_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(incr_block)

        # Increment
        self.builder.position_at_end(incr_block)
        current = self._load_variable(var_name, node)
        incremented = self.builder.add(current, step)
        self._store_variable(var_name, incremented, "int")
        self.builder.branch(cond_block)

        # Else (runs if loop completed without break)
        if else_block:
            self.builder.position_at_end(else_block)
            self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)

    def _emit_with(self, node: ast.With) -> None:
        """Emit `with expr as var: body`.

        Desugars to:
            mgr = expr
            val = mgr.__enter__()
            var = val             # (if `as var` present)
            try:
                body
            finally:
                mgr.__exit__(None, None, None)

        Note: exception suppression (__exit__ returning True) is not
        yet implemented — __exit__ is always called for cleanup, but
        its return value is ignored.
        """
        for item in node.items:
            ctx_expr = item.context_expr
            opt_var = item.optional_vars  # ast.Name or None

            # Evaluate the context manager
            mgr = self._emit_expr_value(ctx_expr)
            # Ensure mgr is a pointer (object)
            if isinstance(mgr.type, ir.IntType) and mgr.type.width == 64:
                mgr = self.builder.inttoptr(mgr, i8_ptr, name="with.mgr")

            # Call __enter__() → returns a value (the `as` target)
            enter_name = self._make_string_constant("__enter__")
            enter_result = self.builder.call(
                self.runtime["obj_call_method0"], [mgr, enter_name])

            # Bind `as var` if present
            if opt_var is not None and isinstance(opt_var, ast.Name):
                # Determine type: if __enter__ returns self, tag as obj
                cls = self._infer_object_class(ctx_expr)
                if cls:
                    val_ptr = self.builder.inttoptr(
                        enter_result, i8_ptr, name="with.val")
                    self._store_variable(opt_var.id, val_ptr, "obj")
                    self._obj_var_class[opt_var.id] = cls
                else:
                    self._store_variable(
                        opt_var.id, enter_result, "int")

            # Store mgr pointer for the finally block's __exit__ call.
            # Use a local alloca so it survives across basic blocks.
            mgr_alloca = self._create_entry_alloca(i8_ptr, "with.mgr.save")
            if isinstance(mgr.type, ir.IntType):
                mgr = self.builder.inttoptr(mgr, i8_ptr)
            self.builder.store(mgr, mgr_alloca)

            # Build a synthetic try/finally AST to reuse _emit_try.
            # The finally body calls __exit__(None, None, None).
            # Instead of building fake AST nodes, emit the IR directly:
            finally_block = self._new_block("with.finally")
            end_block = self._new_block("with.end")

            # Push finally onto stack (for returns inside the with body)
            # We'll emit the finally body inline, but also need it for
            # the _finally_stack so `return` inside with-body triggers it.
            # Create a dummy finalbody list — we'll emit manually.
            self._finally_stack.append([])  # placeholder

            # Emit with-body in try context
            saved_in_try = self._in_try_block
            saved_exc_target = getattr(self, '_try_except_target', None)
            self._in_try_block = True
            self._try_except_target = finally_block

            for stmt in node.body:
                if self.builder.block.is_terminated:
                    break
                self._emit_stmt(stmt)
                if self.builder.block.is_terminated:
                    break
                # Check for pending exception after each statement
                pending = self.builder.call(
                    self.runtime["exc_pending"], [])
                is_exc = self.builder.icmp_signed(
                    "!=", pending, ir.Constant(i32, 0))
                cont_block = self._new_block("with.cont")
                self.builder.cbranch(is_exc, finally_block, cont_block)
                self.builder.position_at_end(cont_block)

            self._in_try_block = saved_in_try
            self._try_except_target = saved_exc_target
            self._finally_stack.pop()

            # Normal exit → finally
            if not self.builder.block.is_terminated:
                self.builder.branch(finally_block)

            # Finally block: call __exit__(None, None, None)
            self.builder.position_at_end(finally_block)
            saved_mgr = self.builder.load(mgr_alloca, name="with.mgr.r")
            exit_name = self._make_string_constant("__exit__")
            # Pass 3 None args as i64(0) — matches obj_call_method3 ABI
            zero = ir.Constant(i64, 0)
            self.builder.call(
                self.runtime["obj_call_method3"],
                [saved_mgr, exit_name, zero, zero, zero])
            self.builder.branch(end_block)

            self.builder.position_at_end(end_block)

    def _emit_match(self, node: ast.Match) -> None:
        """Emit match/case statement (Python 3.10+ structural pattern matching).

        Supports: literal patterns, capture patterns, wildcard (_),
        OR patterns (|), and guard clauses (if cond).
        """
        subject = self._emit_expr_value(node.subject)
        end_block = self._new_block("match.end")

        for case in node.cases:
            pattern = case.pattern
            next_case = self._new_block("match.next")
            body_block = self._new_block("match.body")

            matched = self._emit_match_pattern(subject, pattern, node)

            # Guard: case N if cond:
            if case.guard is not None and matched is not None:
                guard_block = self._new_block("match.guard")
                self.builder.cbranch(matched, guard_block, next_case)
                self.builder.position_at_end(guard_block)
                guard_cond = self._emit_condition(case.guard)
                self.builder.cbranch(guard_cond, body_block, next_case)
            elif matched is not None:
                self.builder.cbranch(matched, body_block, next_case)
            else:
                # Wildcard or capture-only → always matches
                self.builder.branch(body_block)

            self.builder.position_at_end(body_block)
            self._emit_stmts(case.body)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

            self.builder.position_at_end(next_case)

        # If no case matched, fall through
        if not self.builder.block.is_terminated:
            self.builder.branch(end_block)
        self.builder.position_at_end(end_block)

    def _emit_match_pattern(self, subject, pattern, node):
        """Emit a match pattern check. Returns an i1 condition or None
        for wildcard/capture patterns that always match."""
        # MatchValue: case 1, case "hello", etc.
        if isinstance(pattern, ast.MatchValue):
            val = self._emit_expr_value(pattern.value)
            if isinstance(subject.type, ir.IntType) and isinstance(val.type, ir.IntType):
                return self.builder.icmp_signed("==", subject, val)
            elif isinstance(subject.type, ir.PointerType) and isinstance(val.type, ir.PointerType):
                cmp = self.builder.call(self.runtime["str_compare"], [subject, val])
                return self.builder.icmp_signed("==", cmp, ir.Constant(i64, 0))
            elif isinstance(subject.type, ir.DoubleType) and isinstance(val.type, ir.DoubleType):
                return self.builder.fcmp_ordered("==", subject, val)
            # Type mismatch → no match
            return ir.Constant(ir.IntType(1), 0)

        # MatchStar / MatchAs with name: case n → capture
        if isinstance(pattern, ast.MatchAs):
            if pattern.pattern is not None:
                # case pattern as name
                inner = self._emit_match_pattern(subject, pattern.pattern, node)
                if pattern.name:
                    tag = self._llvm_type_tag(subject)
                    self._store_variable(pattern.name, subject, tag)
                return inner
            if pattern.name is None:
                # case _ → wildcard, always matches
                return None
            # case name → capture, always matches
            tag = self._llvm_type_tag(subject)
            self._store_variable(pattern.name, subject, tag)
            return None

        # MatchOr: case 1 | 2 | 3
        if isinstance(pattern, ast.MatchOr):
            result = ir.Constant(ir.IntType(1), 0)
            for p in pattern.patterns:
                cond = self._emit_match_pattern(subject, p, node)
                if cond is None:
                    return None  # wildcard in OR → always matches
                result = self.builder.or_(result, cond)
            return result

        # MatchSequence: case (a, b) — tuple/list unpacking
        if isinstance(pattern, ast.MatchSequence):
            # Check length matches
            length = self.builder.call(self.runtime["list_length"], [subject])
            len_ok = self.builder.icmp_signed(
                "==", length, ir.Constant(i64, len(pattern.patterns)))
            # For each element, extract and match/bind
            for i, p in enumerate(pattern.patterns):
                if isinstance(p, ast.MatchAs) and p.name and p.pattern is None:
                    # Capture: bind element to name
                    elem = self._list_get_as_bare(
                        subject, ir.Constant(i64, i), "int")
                    self._store_variable(p.name, elem, "int")
            return len_ok

        # Fallback: unsupported pattern
        raise CodeGenError(
            f"Unsupported match pattern: {type(pattern).__name__}", node)

    def _generator_needs_cpython(self, node: ast.FunctionDef) -> bool:
        """Check if a generator function needs CPython's coroutine support.
        Generators that use `yield` as an expression (x = yield),
        or are called with .send()/.throw()/.close(), need true
        coroutine semantics that our list-collection approach can't provide."""
        for child in ast.walk(node):
            # yield used as an expression in an assignment
            if isinstance(child, ast.Assign) and isinstance(child.value, ast.Yield):
                return True
            # yield used as expression in augmented assignment
            if isinstance(child, ast.AugAssign) and isinstance(child.value, ast.Yield):
                return True
        return False

    def _emit_cpython_generator(self, node: ast.FunctionDef, effective_name: str) -> None:
        """Compile a generator function through CPython bridge.
        The function is serialized as Python source and exec'd in CPython,
        producing a real Python generator that supports send/close/throw."""
        func_source = ast.unparse(ast.Module(body=[node], type_ignores=[]))
        source_ptr = self._make_string_constant(func_source)
        name_ptr = self._make_string_constant(effective_name)
        func_ptr = self.builder.call(
            self.runtime["cpython_exec_get"], [source_ptr, name_ptr])
        self._store_variable(effective_name, func_ptr, "pyobj")

    def _emit_yield(self, node: ast.Yield) -> None:
        """Emit `yield val` — appends to the generator's result list.
        Simple generator implementation: collects all yielded values
        into a list. Does NOT support send/close/throw or lazy evaluation.
        """
        gen_list = getattr(self, '_gen_list', None)
        if gen_list is None:
            raise CodeGenError("yield outside generator function", node)
        if node.value is not None:
            self._emit_list_append_expr(gen_list, node.value)
        else:
            # yield with no value → append None
            none_tag = ir.Constant(i32, FPY_TAG_NONE)
            none_data = ir.Constant(i64, 0)
            self.builder.call(self.runtime["list_append_fv"],
                              [gen_list, none_tag, none_data])

    def _emit_yield_from(self, node: ast.YieldFrom) -> None:
        """Emit `yield from iterable` — extends the generator's result list."""
        gen_list = getattr(self, '_gen_list', None)
        if gen_list is None:
            raise CodeGenError("yield from outside generator function", node)
        source = self._emit_expr_value(node.value)
        if isinstance(source.type, ir.PointerType):
            self.builder.call(self.runtime["list_extend"], [gen_list, source])
        else:
            raise CodeGenError("yield from requires an iterable", node)

    # Modules with native implementations (no CPython bridge needed)
    _NATIVE_MODULES = {"math"}

    # Native math constants
    _MATH_CONSTANTS = {
        "pi": 3.141592653589793,
        "e": 2.718281828459045,
        "tau": 6.283185307179586,
        "inf": float("inf"),
    }

    # Native math functions: maps Python name → (runtime key, n_args)
    _MATH_FUNCTIONS = {
        "sqrt": ("math_sqrt", 1), "sin": ("math_sin", 1),
        "cos": ("math_cos", 1), "tan": ("math_tan", 1),
        "asin": ("math_asin", 1), "acos": ("math_acos", 1),
        "atan": ("math_atan", 1), "atan2": ("math_atan2", 2),
        "exp": ("math_exp", 1), "log": ("math_log", 1),
        "log2": ("math_log2", 1), "log10": ("math_log10", 1),
        "ceil": ("math_ceil", 1), "floor": ("math_floor", 1),
        "fabs": ("math_fabs", 1), "pow": ("math_pow", 2),
        "fmod": ("math_fmod", 2),
        "sinh": ("math_sinh", 1), "cosh": ("math_cosh", 1),
        "tanh": ("math_tanh", 1),
    }

    def _emit_import(self, node: ast.Import) -> None:
        """Emit `import module` — loads a CPython module (.pyd or .py)
        via the CPython C API and stores the PyObject* as a variable."""
        for alias in node.names:
            mod_name = alias.name
            var_name = alias.asname if alias.asname else mod_name

            # Native module: mark as native, no CPython bridge needed
            if mod_name in self._NATIVE_MODULES:
                if not hasattr(self, '_native_modules'):
                    self._native_modules = set()
                self._native_modules.add(var_name)
                # Store a dummy value — attribute access is intercepted
                self._store_variable(var_name, ir.Constant(i64, 0), "native_mod")
                continue

            # Create a global to hold the module PyObject*
            if mod_name not in self._cpython_modules:
                gvar = ir.GlobalVariable(
                    self.module, i8_ptr,
                    name=f"fastpy.pymod.{mod_name}")
                gvar.initializer = ir.Constant(i8_ptr, None)
                gvar.linkage = "private"
                self._cpython_modules[mod_name] = gvar

            # Call fpy_cpython_import(name) → PyObject*
            name_ptr = self._make_string_constant(mod_name)
            mod_ptr = self.builder.call(
                self.runtime["cpython_import"], [name_ptr])
            self.builder.store(mod_ptr, self._cpython_modules[mod_name])

            # For dotted imports (e.g. `import os.path`), Python binds
            # the top-level module name. `import os.path` creates `os`.
            if "." in var_name:
                top_name = var_name.split(".")[0]
                # Import the top-level module too
                if top_name not in self._cpython_modules:
                    gvar = ir.GlobalVariable(
                        self.module, i8_ptr,
                        name=f"fastpy.pymod.{top_name}")
                    gvar.initializer = ir.Constant(i8_ptr, None)
                    gvar.linkage = "private"
                    self._cpython_modules[top_name] = gvar
                top_name_ptr = self._make_string_constant(top_name)
                top_mod = self.builder.call(
                    self.runtime["cpython_import"], [top_name_ptr])
                self.builder.store(top_mod, self._cpython_modules[top_name])
                self._store_variable(top_name, top_mod, "pyobj")
            else:
                # Store as a local variable with "pyobj" tag
                self._store_variable(var_name, mod_ptr, "pyobj")

    def _emit_import_from(self, node: ast.ImportFrom) -> None:
        """Emit `from module import name1, name2`."""
        mod_name = node.module

        # Native module: store function markers instead of pyobj
        if mod_name in self._NATIVE_MODULES:
            if not hasattr(self, '_native_imports'):
                self._native_imports = {}
            for alias in node.names:
                attr_name = alias.name
                var_name = alias.asname if alias.asname else attr_name
                self._native_imports[var_name] = (mod_name, attr_name)
                # Store dummy — calls are intercepted in _emit_call_expr
                self._store_variable(var_name, ir.Constant(i64, 0), "native_func")
            return

        if mod_name not in self._cpython_modules:
            gvar = ir.GlobalVariable(
                self.module, i8_ptr,
                name=f"fastpy.pymod.{mod_name}")
            gvar.initializer = ir.Constant(i8_ptr, None)
            gvar.linkage = "private"
            self._cpython_modules[mod_name] = gvar

        name_ptr = self._make_string_constant(mod_name)
        mod_ptr = self.builder.call(
            self.runtime["cpython_import"], [name_ptr])
        self.builder.store(mod_ptr, self._cpython_modules[mod_name])

        for alias in node.names:
            attr_name = alias.name
            var_name = alias.asname if alias.asname else attr_name
            attr_ptr = self._make_string_constant(attr_name)
            pyobj = self.builder.call(
                self.runtime["cpython_getattr"], [mod_ptr, attr_ptr])
            # Check if the attribute is callable (function) or a value
            # (constant like pi). For constants, convert to native FpyValue
            # at import time. For callables, keep as pyobj.
            # Use cpython_to_fv to convert — if it's a callable, it will
            # come back as OBJ tag (opaque). Store as pyobj either way
            # since we need the callable pointer for function calls.
            self._store_variable(var_name, pyobj, "pyobj")

    def _emit_async_funcdef(self, node: ast.AsyncFunctionDef) -> None:
        """Emit `async def f(): ...` by compiling through CPython bridge.
        Async functions require CPython's asyncio runtime, so we serialize
        the source code and exec it in CPython, retrieving the callable."""
        # Collect module references the async body needs
        imports = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                name = child.value.id
                if name in self._cpython_modules or name in ("asyncio",):
                    imports.add(name)
            if isinstance(child, ast.Name) and child.id in self._cpython_modules:
                imports.add(child.id)

        # Build source code from AST
        import_stmts = "\n".join(f"import {m}" for m in sorted(imports))
        func_source = ast.unparse(ast.Module(body=[node], type_ignores=[]))
        full_source = f"{import_stmts}\n{func_source}" if imports else func_source

        source_ptr = self._make_string_constant(full_source)
        name_ptr = self._make_string_constant(node.name)
        func_ptr = self.builder.call(
            self.runtime["cpython_exec_get"], [source_ptr, name_ptr])
        self._store_variable(node.name, func_ptr, "pyobj")

    def _emit_try_star(self, node: ast.TryStar) -> None:
        """Emit try/except* (exception groups).
        Simplified implementation: when ExceptionGroup is raised, the inner
        exception types are stored. except* matches against the inner types.
        For the common case of single-type groups, this is semantically
        equivalent to CPython's behavior."""
        # TryStar has the same structure as Try: body, handlers, orelse, finalbody
        has_except = bool(node.handlers)
        has_finally = bool(node.finalbody)

        except_block = self._new_block("trystar.except") if has_except else None
        finally_block = self._new_block("trystar.finally") if has_finally else None
        end_block = self._new_block("trystar.end")

        if has_finally:
            self._finally_stack.append(node.finalbody)

        # Emit try body with exception checking
        saved_in_try = self._in_try_block
        saved_exc_target = getattr(self, '_try_except_target', None)
        self._in_try_block = True
        exc_target = except_block if except_block else (finally_block if finally_block else end_block)
        self._try_except_target = exc_target
        for stmt in node.body:
            if self.builder.block.is_terminated:
                break
            self._emit_stmt(stmt)
            if self.builder.block.is_terminated:
                break
            pending = self.builder.call(self.runtime["exc_pending"], [])
            is_exc = self.builder.icmp_signed("!=", pending, ir.Constant(i32, 0))
            cont_block = self._new_block("trystar.cont")
            self.builder.cbranch(is_exc, exc_target, cont_block)
            self.builder.position_at_end(cont_block)

        self._in_try_block = saved_in_try
        self._try_except_target = saved_exc_target
        if not self.builder.block.is_terminated:
            if finally_block:
                self.builder.branch(finally_block)
            else:
                self.builder.branch(end_block)

        # Except* handlers — match against inner exception types for groups
        if has_except:
            self.builder.position_at_end(except_block)
            exc_type = self.builder.call(self.runtime["exc_get_type"], [])
            saved_exc_type_alloca = self._create_entry_alloca(i32, "saved.exc.type")
            saved_exc_msg_alloca = self._create_entry_alloca(i8_ptr, "saved.exc.msg")
            self.builder.store(exc_type, saved_exc_type_alloca)
            saved_msg = self.builder.call(self.runtime["exc_get_msg"], [])
            self.builder.store(saved_msg, saved_exc_msg_alloca)
            self._saved_exc_type = saved_exc_type_alloca
            self._saved_exc_msg = saved_exc_msg_alloca

            # For except*, also check the group's inner type.
            # The inner type is stored via exc_get_group_inner_type().
            # If the exception IS an ExceptionGroup, we match handlers
            # against the inner type; otherwise fall back to normal matching.
            exc_group_name = self._make_string_constant("ExceptionGroup")
            expected_group_id = self.builder.call(
                self.runtime["exc_name_to_id"], [exc_group_name])
            is_group = self.builder.icmp_signed("==", exc_type, expected_group_id)
            inner_type = self.builder.call(self.runtime["exc_get_group_inner"], [])
            # Use inner type if this is a group, otherwise use the exception type itself
            effective_type = self.builder.select(is_group, inner_type, exc_type)

            for handler in node.handlers:
                handler_block = self._new_block("exceptstar.handler")
                next_handler = self._new_block("exceptstar.next")

                if handler.type is not None and isinstance(handler.type, ast.Name):
                    exc_name = self._make_string_constant(handler.type.id)
                    expected_id = self.builder.call(
                        self.runtime["exc_name_to_id"], [exc_name])
                    matches = self.builder.icmp_signed("==", effective_type, expected_id)
                    self.builder.cbranch(matches, handler_block, next_handler)
                else:
                    self.builder.branch(handler_block)

                self.builder.position_at_end(handler_block)
                if handler.name:
                    msg = self.builder.call(self.runtime["exc_get_msg"], [])
                    self._store_variable(handler.name, msg, "str")
                self.builder.call(self.runtime["exc_clear"], [])
                self._emit_stmts(handler.body)
                if not self.builder.block.is_terminated:
                    if finally_block:
                        self.builder.branch(finally_block)
                    else:
                        self.builder.branch(end_block)

                self.builder.position_at_end(next_handler)

            if not self.builder.block.is_terminated:
                if finally_block:
                    self.builder.branch(finally_block)
                else:
                    self.builder.call(self.runtime["exc_unhandled"], [])
                    self.builder.unreachable()

        if has_finally:
            self._finally_stack.pop()

        if has_finally:
            self.builder.position_at_end(finally_block)
            self._emit_stmts(node.finalbody)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)

    def _emit_cpython_method_call(self, node: ast.Call) -> ir.Value:
        """Emit a call to a function accessed via CPython module attribute.
        E.g., math.sqrt(4.0) where math is a pyobj-tagged variable."""
        attr = node.func  # ast.Attribute
        # Get the module/object pointer
        obj = self._emit_expr_value(attr.value)
        if isinstance(obj.type, ir.IntType):
            obj = self.builder.inttoptr(obj, i8_ptr)
        # Get the callable attribute
        attr_name = self._make_string_constant(attr.attr)
        callable_ptr = self.builder.call(
            self.runtime["cpython_getattr"], [obj, attr_name])

        # Prepare output slots
        out_tag = self._create_entry_alloca(i32, "pycall.tag")
        out_data = self._create_entry_alloca(i64, "pycall.data")

        # If there are keyword arguments, use the general call_kw path
        if node.keywords:
            n_pos = len(node.args)
            n_kw = len(node.keywords)
            # Build positional arg arrays
            tags_alloca = self.builder.alloca(
                ir.ArrayType(i32, max(n_pos, 1)), name="kw.tags")
            data_alloca = self.builder.alloca(
                ir.ArrayType(i64, max(n_pos, 1)), name="kw.data")
            for i, arg_node in enumerate(node.args):
                val = self._emit_expr_value(arg_node)
                tag, data = self._bare_to_tag_data(val, arg_node)
                tag_ptr = self.builder.gep(tags_alloca,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)])
                data_ptr = self.builder.gep(data_alloca,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)])
                self.builder.store(ir.Constant(i32, tag), tag_ptr)
                self.builder.store(data, data_ptr)
            # Build keyword arg arrays
            names_alloca = self.builder.alloca(
                ir.ArrayType(i8_ptr, n_kw), name="kw.names")
            kw_tags_alloca = self.builder.alloca(
                ir.ArrayType(i32, n_kw), name="kw.ktags")
            kw_data_alloca = self.builder.alloca(
                ir.ArrayType(i64, n_kw), name="kw.kdata")
            for i, kw in enumerate(node.keywords):
                name_ptr = self._make_string_constant(kw.arg)
                val = self._emit_expr_value(kw.value)
                tag, data = self._bare_to_tag_data(val, kw.value)
                n_ptr = self.builder.gep(names_alloca,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)])
                t_ptr = self.builder.gep(kw_tags_alloca,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)])
                d_ptr = self.builder.gep(kw_data_alloca,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)])
                self.builder.store(name_ptr, n_ptr)
                self.builder.store(ir.Constant(i32, tag), t_ptr)
                self.builder.store(data, d_ptr)
            # Call
            tags_base = self.builder.gep(tags_alloca,
                [ir.Constant(i32, 0), ir.Constant(i32, 0)])
            data_base = self.builder.gep(data_alloca,
                [ir.Constant(i32, 0), ir.Constant(i32, 0)])
            names_base = self.builder.gep(names_alloca,
                [ir.Constant(i32, 0), ir.Constant(i32, 0)])
            kt_base = self.builder.gep(kw_tags_alloca,
                [ir.Constant(i32, 0), ir.Constant(i32, 0)])
            kd_base = self.builder.gep(kw_data_alloca,
                [ir.Constant(i32, 0), ir.Constant(i32, 0)])
            self.builder.call(self.runtime["cpython_call_kw"],
                              [callable_ptr,
                               ir.Constant(i32, n_pos), tags_base, data_base,
                               ir.Constant(i32, n_kw), names_base, kt_base, kd_base,
                               out_tag, out_data])
            tag_val = self.builder.load(out_tag)
            data_val = self.builder.load(out_data)
            return self._fv_build_from_slots(tag_val, data_val)

        n_args = len(node.args)
        if n_args == 0:
            self.builder.call(self.runtime["cpython_call0"],
                              [callable_ptr, out_tag, out_data])
        elif n_args == 1:
            arg = self._emit_expr_value(node.args[0])
            tag, data = self._bare_to_tag_data(arg, node.args[0])
            self.builder.call(self.runtime["cpython_call1"],
                              [callable_ptr,
                               ir.Constant(i32, tag), data,
                               out_tag, out_data])
        elif n_args == 2:
            a1 = self._emit_expr_value(node.args[0])
            t1, d1 = self._bare_to_tag_data(a1, node.args[0])
            a2 = self._emit_expr_value(node.args[1])
            t2, d2 = self._bare_to_tag_data(a2, node.args[1])
            self.builder.call(self.runtime["cpython_call2"],
                              [callable_ptr,
                               ir.Constant(i32, t1), d1,
                               ir.Constant(i32, t2), d2,
                               out_tag, out_data])
        elif n_args == 3:
            a1 = self._emit_expr_value(node.args[0])
            t1, d1 = self._bare_to_tag_data(a1, node.args[0])
            a2 = self._emit_expr_value(node.args[1])
            t2, d2 = self._bare_to_tag_data(a2, node.args[1])
            a3 = self._emit_expr_value(node.args[2])
            t3, d3 = self._bare_to_tag_data(a3, node.args[2])
            self.builder.call(self.runtime["cpython_call3"],
                              [callable_ptr,
                               ir.Constant(i32, t1), d1,
                               ir.Constant(i32, t2), d2,
                               ir.Constant(i32, t3), d3,
                               out_tag, out_data])
        else:
            raise CodeGenError(
                f"CPython call with {n_args} args not yet supported (max 3)",
                node)

        # Return the result — determine bare type from tag
        tag_val = self.builder.load(out_tag)
        data_val = self.builder.load(out_data)

        # For now, return as FpyValue and let the caller handle it
        return self._fv_build_from_slots(tag_val, data_val)

    def _emit_cpython_call_raw(self, node: ast.Call) -> ir.Value:
        """Emit a CPython method call that returns the raw PyObject* (i8_ptr).
        Used when the result will be stored as pyobj for downstream operations."""
        attr = node.func  # ast.Attribute
        obj = self._emit_expr_value(attr.value)
        if isinstance(obj.type, ir.IntType):
            obj = self.builder.inttoptr(obj, i8_ptr)
        attr_name = self._make_string_constant(attr.attr)
        callable_ptr = self.builder.call(
            self.runtime["cpython_getattr"], [obj, attr_name])

        # If there are keyword arguments, use the general call_kw_raw path
        if node.keywords:
            n_pos = len(node.args)
            n_kw = len(node.keywords)
            tags_alloca = self.builder.alloca(
                ir.ArrayType(i32, max(n_pos, 1)), name="raw.tags")
            data_alloca = self.builder.alloca(
                ir.ArrayType(i64, max(n_pos, 1)), name="raw.data")
            for i, arg_node in enumerate(node.args):
                val = self._emit_expr_value(arg_node)
                tag, data = self._bare_to_tag_data(val, arg_node)
                self.builder.store(ir.Constant(i32, tag),
                    self.builder.gep(tags_alloca,
                        [ir.Constant(i32, 0), ir.Constant(i32, i)]))
                self.builder.store(data,
                    self.builder.gep(data_alloca,
                        [ir.Constant(i32, 0), ir.Constant(i32, i)]))
            names_alloca = self.builder.alloca(
                ir.ArrayType(i8_ptr, n_kw), name="raw.knames")
            kt_alloca = self.builder.alloca(
                ir.ArrayType(i32, n_kw), name="raw.ktags")
            kd_alloca = self.builder.alloca(
                ir.ArrayType(i64, n_kw), name="raw.kdata")
            for i, kw in enumerate(node.keywords):
                name_ptr = self._make_string_constant(kw.arg)
                val = self._emit_expr_value(kw.value)
                tag, data = self._bare_to_tag_data(val, kw.value)
                self.builder.store(name_ptr,
                    self.builder.gep(names_alloca,
                        [ir.Constant(i32, 0), ir.Constant(i32, i)]))
                self.builder.store(ir.Constant(i32, tag),
                    self.builder.gep(kt_alloca,
                        [ir.Constant(i32, 0), ir.Constant(i32, i)]))
                self.builder.store(data,
                    self.builder.gep(kd_alloca,
                        [ir.Constant(i32, 0), ir.Constant(i32, i)]))
            return self.builder.call(self.runtime["cpython_call_kw_raw"],
                [callable_ptr,
                 ir.Constant(i32, n_pos),
                 self.builder.gep(tags_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)]),
                 self.builder.gep(data_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)]),
                 ir.Constant(i32, n_kw),
                 self.builder.gep(names_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)]),
                 self.builder.gep(kt_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)]),
                 self.builder.gep(kd_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)])])

        n_args = len(node.args)
        if n_args == 0:
            return self.builder.call(
                self.runtime["cpython_call0_raw"], [callable_ptr])
        elif n_args == 1:
            arg = self._emit_expr_value(node.args[0])
            tag, data = self._bare_to_tag_data(arg, node.args[0])
            return self.builder.call(
                self.runtime["cpython_call1_raw"],
                [callable_ptr, ir.Constant(i32, tag), data])
        elif n_args == 2:
            a1 = self._emit_expr_value(node.args[0])
            t1, d1 = self._bare_to_tag_data(a1, node.args[0])
            a2 = self._emit_expr_value(node.args[1])
            t2, d2 = self._bare_to_tag_data(a2, node.args[1])
            return self.builder.call(
                self.runtime["cpython_call2_raw"],
                [callable_ptr,
                 ir.Constant(i32, t1), d1,
                 ir.Constant(i32, t2), d2])
        else:
            # Fall back to FV path for 3+ args
            fv = self._emit_cpython_method_call(node)
            data = self.builder.extract_value(fv, 1)
            return self.builder.inttoptr(data, i8_ptr)

    def _emit_cpython_direct_call(self, node: ast.Call) -> None:
        """Emit a call to a pyobj-tagged callable (statement context)."""
        self._emit_cpython_direct_call_expr(node)

    def _emit_cpython_direct_call_expr(self, node: ast.Call) -> ir.Value:
        """Emit a call to a pyobj-tagged callable (expression context).
        Returns an FpyValue struct."""
        name = node.func.id
        callable_ptr = self._load_variable(name, node)
        if isinstance(callable_ptr.type, ir.IntType):
            callable_ptr = self.builder.inttoptr(callable_ptr, i8_ptr)

        out_tag = self._create_entry_alloca(i32, "pycall.tag")
        out_data = self._create_entry_alloca(i64, "pycall.data")

        n_args = len(node.args)
        if n_args == 0:
            self.builder.call(self.runtime["cpython_call0"],
                              [callable_ptr, out_tag, out_data])
        elif n_args == 1:
            arg = self._emit_expr_value(node.args[0])
            tag, data = self._bare_to_tag_data(arg, node.args[0])
            self.builder.call(self.runtime["cpython_call1"],
                              [callable_ptr,
                               ir.Constant(i32, tag), data,
                               out_tag, out_data])
        elif n_args == 2:
            a1 = self._emit_expr_value(node.args[0])
            t1, d1 = self._bare_to_tag_data(a1, node.args[0])
            a2 = self._emit_expr_value(node.args[1])
            t2, d2 = self._bare_to_tag_data(a2, node.args[1])
            self.builder.call(self.runtime["cpython_call2"],
                              [callable_ptr,
                               ir.Constant(i32, t1), d1,
                               ir.Constant(i32, t2), d2,
                               out_tag, out_data])
        elif n_args == 3:
            a1 = self._emit_expr_value(node.args[0])
            t1, d1 = self._bare_to_tag_data(a1, node.args[0])
            a2 = self._emit_expr_value(node.args[1])
            t2, d2 = self._bare_to_tag_data(a2, node.args[1])
            a3 = self._emit_expr_value(node.args[2])
            t3, d3 = self._bare_to_tag_data(a3, node.args[2])
            self.builder.call(self.runtime["cpython_call3"],
                              [callable_ptr,
                               ir.Constant(i32, t1), d1,
                               ir.Constant(i32, t2), d2,
                               ir.Constant(i32, t3), d3,
                               out_tag, out_data])
        else:
            raise CodeGenError(
                f"CPython call with {n_args} args not yet supported (max 3)", node)

        tag_val = self.builder.load(out_tag)
        data_val = self.builder.load(out_data)
        return self._fv_build_from_slots(tag_val, data_val)

    def _emit_try(self, node: ast.Try) -> None:
        """Emit try/except/finally using flag-based exception checking."""
        has_except = bool(node.handlers)
        has_finally = bool(node.finalbody)

        except_block = self._new_block("try.except") if has_except else None
        finally_block = self._new_block("try.finally") if has_finally else None
        end_block = self._new_block("try.end")

        # Push finally body — in scope for try body AND except handlers
        if has_finally:
            self._finally_stack.append(node.finalbody)

        # Emit try body — after each statement, check for pending exception
        saved_in_try = self._in_try_block
        saved_exc_target = getattr(self, '_try_except_target', None)
        self._in_try_block = True
        exc_target = except_block if except_block else (finally_block if finally_block else end_block)
        self._try_except_target = exc_target
        for stmt in node.body:
            if self.builder.block.is_terminated:
                break
            self._emit_stmt(stmt)
            if self.builder.block.is_terminated:
                break
            # Check for pending exception after each statement
            pending = self.builder.call(self.runtime["exc_pending"], [])
            is_exc = self.builder.icmp_signed("!=", pending, ir.Constant(i32, 0))
            cont_block = self._new_block("try.cont")
            exc_target = except_block if except_block else (finally_block if finally_block else end_block)
            self.builder.cbranch(is_exc, exc_target, cont_block)
            self.builder.position_at_end(cont_block)

        self._in_try_block = saved_in_try
        self._try_except_target = saved_exc_target
        # No exception — run else block (if present), then jump to finally/end
        has_else = bool(node.orelse)
        if not self.builder.block.is_terminated:
            if has_else:
                else_block = self._new_block("try.else")
                self.builder.branch(else_block)
                self.builder.position_at_end(else_block)
                self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                if finally_block:
                    self.builder.branch(finally_block)
                else:
                    self.builder.branch(end_block)

        # Except handlers
        if has_except:
            self.builder.position_at_end(except_block)
            exc_type = self.builder.call(self.runtime["exc_get_type"], [])
            # Save exception info for bare `raise` (re-raise) support.
            # These allocas hold the type+msg so exc_clear doesn't lose them.
            saved_exc_type_alloca = self._create_entry_alloca(i32, "saved.exc.type")
            saved_exc_msg_alloca = self._create_entry_alloca(i8_ptr, "saved.exc.msg")
            self.builder.store(exc_type, saved_exc_type_alloca)
            saved_msg = self.builder.call(self.runtime["exc_get_msg"], [])
            self.builder.store(saved_msg, saved_exc_msg_alloca)
            self._saved_exc_type = saved_exc_type_alloca
            self._saved_exc_msg = saved_exc_msg_alloca

            for handler in node.handlers:
                if handler.type is None:
                    # bare except:
                    if handler.name:
                        msg = self.builder.call(self.runtime["exc_get_msg"], [])
                        self._store_variable(handler.name, msg, "str")
                    self.builder.call(self.runtime["exc_clear"], [])
                    self._emit_stmts(handler.body)
                    if not self.builder.block.is_terminated:
                        if finally_block:
                            self.builder.branch(finally_block)
                        else:
                            self.builder.branch(end_block)
                else:
                    handler_block = self._new_block("except.handler")
                    next_handler = self._new_block("except.next")

                    if isinstance(handler.type, ast.Name):
                        exc_name = self._make_string_constant(handler.type.id)
                        expected_id = self.builder.call(
                            self.runtime["exc_name_to_id"], [exc_name])
                        matches = self.builder.icmp_signed("==", exc_type, expected_id)
                        self.builder.cbranch(matches, handler_block, next_handler)
                    else:
                        self.builder.branch(handler_block)

                    self.builder.position_at_end(handler_block)
                    if handler.name:
                        msg = self.builder.call(self.runtime["exc_get_msg"], [])
                        self._store_variable(handler.name, msg, "str")
                    self.builder.call(self.runtime["exc_clear"], [])
                    self._emit_stmts(handler.body)
                    if not self.builder.block.is_terminated:
                        if finally_block:
                            self.builder.branch(finally_block)
                        else:
                            self.builder.branch(end_block)

                    self.builder.position_at_end(next_handler)

            # No handler matched — unhandled exception
            if not self.builder.block.is_terminated:
                if finally_block:
                    self.builder.branch(finally_block)
                else:
                    self.builder.call(self.runtime["exc_unhandled"], [])
                    self.builder.unreachable()

        # Pop finally from stack before emitting the finally block itself
        # (so returns inside finally don't re-emit itself)
        if has_finally:
            self._finally_stack.pop()

        # Finally block
        if has_finally:
            self.builder.position_at_end(finally_block)
            self._emit_stmts(node.finalbody)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)

    def _emit_raise(self, node: ast.Raise) -> None:
        """Emit raise ExcType('msg'). Sets the exception flag; caller checks it."""
        if node.exc is None:
            # bare raise — re-raise the saved exception from the
            # enclosing except handler.
            if hasattr(self, '_saved_exc_type') and self._saved_exc_type:
                exc_type = self.builder.load(self._saved_exc_type)
                exc_msg = self.builder.load(self._saved_exc_msg)
                self.builder.call(self.runtime["raise"], [exc_type, exc_msg])
            return

        if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
            exc_name = node.exc.func.id
            name_ptr = self._make_string_constant(exc_name)
            exc_id = self.builder.call(self.runtime["exc_name_to_id"], [name_ptr])

            # ExceptionGroup("g", [ValueError("a"), ...]) — store inner type
            if exc_name == "ExceptionGroup" and len(node.exc.args) >= 2:
                group_msg = self._emit_expr_value(node.exc.args[0])
                if not isinstance(group_msg.type, ir.PointerType):
                    group_msg = self._value_to_str(group_msg, node)
                self.builder.call(self.runtime["raise"], [exc_id, group_msg])
                # Extract inner exception type from the list literal
                inner_list = node.exc.args[1]
                if isinstance(inner_list, ast.List) and inner_list.elts:
                    first_exc = inner_list.elts[0]
                    if (isinstance(first_exc, ast.Call)
                            and isinstance(first_exc.func, ast.Name)):
                        inner_name = self._make_string_constant(first_exc.func.id)
                        inner_id = self.builder.call(
                            self.runtime["exc_name_to_id"], [inner_name])
                        self.builder.call(
                            self.runtime["exc_set_group_inner"], [inner_id])
            else:
                # Get message from first argument
                if node.exc.args:
                    msg = self._emit_expr_value(node.exc.args[0])
                    if not isinstance(msg.type, ir.PointerType):
                        msg = self._value_to_str(msg, node)
                else:
                    msg = self._make_string_constant("")
                self.builder.call(self.runtime["raise"], [exc_id, msg])
            # If we're inside a try block, the exception check after this
            # statement will catch it. If not, early-return so the caller
            # can check the exception flag.
            if not self._in_try_block:
                ret_type = self.function.return_value.type
                if isinstance(ret_type, ir.VoidType):
                    self.builder.ret_void()
                elif isinstance(ret_type, ir.LiteralStructType):
                    self.builder.ret(self._fv_none())
                elif isinstance(ret_type, ir.DoubleType):
                    self.builder.ret(ir.Constant(double, 0.0))
                elif isinstance(ret_type, ir.PointerType):
                    self.builder.ret(ir.Constant(ret_type, None))
                else:
                    self.builder.ret(ir.Constant(ret_type, 0))
            return

        # raise ExcName (bare name, no call — no message)
        if isinstance(node.exc, ast.Name):
            exc_name = node.exc.id
            name_ptr = self._make_string_constant(exc_name)
            exc_id = self.builder.call(self.runtime["exc_name_to_id"], [name_ptr])
            msg = self._make_string_constant("")
            self.builder.call(self.runtime["raise"], [exc_id, msg])
            if not self._in_try_block:
                ret_type = self.function.return_value.type
                if isinstance(ret_type, ir.VoidType):
                    self.builder.ret_void()
                elif isinstance(ret_type, ir.LiteralStructType):
                    self.builder.ret(self._fv_none())
                elif isinstance(ret_type, ir.DoubleType):
                    self.builder.ret(ir.Constant(double, 0.0))
                elif isinstance(ret_type, ir.PointerType):
                    self.builder.ret(ir.Constant(ret_type, None))
                else:
                    self.builder.ret(ir.Constant(ret_type, 0))
            return

        raise CodeGenError("Unsupported raise expression", node)

    def _emit_return(self, node: ast.Return) -> None:
        """Emit a return statement.

        If there are pending finally bodies (we're inside one or more
        try-with-finally blocks), emit them in LIFO order before the
        actual return.
        """
        # Evaluate the return value first (side effects happen before finally).
        # When the function returns FpyValue, use _load_or_wrap_fv so that
        # dict subscripts, list subscripts, and FV-backed variables preserve
        # their runtime tag instead of being unwrapped then re-wrapped with
        # a possibly-wrong compile-time tag.
        expected = self.function.return_value.type
        if node.value is not None:
            if isinstance(expected, ir.LiteralStructType):
                # For FV-returning functions, check if the function's static
                # return type is float — if so, promote int returns to float
                # before wrapping, so the runtime tag matches what callers
                # expect.
                ret_info = next(
                    (i for i in self._user_functions.values()
                     if i.func is self.function), None)
                if (ret_info is not None
                        and ret_info.static_ret_type is double):
                    # Force float tag: evaluate, promote int→double, wrap.
                    bare = self._emit_expr_value(node.value)
                    if isinstance(bare.type, ir.IntType):
                        if bare.type.width == 1 or bare.type.width == 32:
                            bare = self.builder.zext(bare, i64)
                        if isinstance(bare.type, ir.IntType):
                            bare = self.builder.sitofp(bare, double)
                    value = self._fv_from_float(bare)
                else:
                    value = self._load_or_wrap_fv(node.value)
            else:
                value = self._emit_expr_value(node.value)
        else:
            value = None

        # When inside a try block, a runtime exception may have been
        # raised during the return expression evaluation (e.g.,
        # `return a / b` where b==0 raises ZeroDivisionError).
        # Check for pending exception and route to the except handler
        # instead of returning.
        if self._in_try_block and node.value is not None:
            exc_target = getattr(self, '_try_except_target', None)
            if exc_target is not None:
                pending = self.builder.call(self.runtime["exc_pending"], [])
                is_exc = self.builder.icmp_signed(
                    "!=", pending, ir.Constant(i32, 0))
                no_exc_block = self._new_block("ret.noexc")
                self.builder.cbranch(is_exc, exc_target, no_exc_block)
                self.builder.position_at_end(no_exc_block)

        # Emit enclosing finally bodies in LIFO order. Take a snapshot to
        # avoid re-entrance if a finally body itself has a try-finally.
        if self._finally_stack:
            for finalbody in reversed(self._finally_stack):
                saved_stack = self._finally_stack
                self._finally_stack = []
                self._emit_stmts(finalbody)
                self._finally_stack = saved_stack
                if self.builder.block.is_terminated:
                    return  # finally block unconditionally terminated

        # Scope cleanup: decref all locals except the return value
        ret_var_name = None
        if node.value is not None and isinstance(node.value, ast.Name):
            ret_var_name = node.value.id
        self._emit_scope_decref(exclude_var=ret_var_name)

        if node.value is None:
            self.builder.ret_void()
        else:
            if isinstance(expected, ir.VoidType):
                # Function was declared void but has return value — ignore value
                self.builder.ret_void()
            elif isinstance(expected, ir.LiteralStructType):
                # value is already an FpyValue from _load_or_wrap_fv above.
                self.builder.ret(value)
            elif value.type != expected:
                # FpyValue → i64 conversion: closures use i64 ABI externally
                # but FV locals internally. Extract the data field and
                # store the tag in fpy_ret_tag so the caller can recover it.
                if (isinstance(expected, ir.IntType)
                        and isinstance(value.type, ir.LiteralStructType)):
                    tag = self.builder.extract_value(value, 0)
                    data = self.builder.extract_value(value, 1)
                    self.builder.call(self.runtime["set_ret_tag"], [tag])
                    self.builder.ret(data)
                    return
                # Type mismatch — try conversion
                if isinstance(expected, ir.IntType) and isinstance(value.type, ir.IntType):
                    if expected.width > value.type.width:
                        value = self.builder.zext(value, expected)
                    else:
                        value = self.builder.trunc(value, expected)
                elif isinstance(expected, ir.IntType) and isinstance(value.type, ir.DoubleType):
                    value = self.builder.fptosi(value, expected)
                elif isinstance(expected, ir.DoubleType) and isinstance(value.type, ir.IntType):
                    value = self.builder.sitofp(value, expected)
                elif isinstance(expected, ir.IntType) and isinstance(value.type, ir.PointerType):
                    value = self.builder.ptrtoint(value, expected)
                elif isinstance(expected, ir.PointerType) and isinstance(value.type, ir.IntType):
                    value = self.builder.inttoptr(value, expected)
                # For closure functions, store the tag before ret
                if (isinstance(expected, ir.IntType)
                        and self.function.name.startswith("fastpy.closure.")):
                    tag = self._infer_ret_tag_for_value(value, node.value)
                    self.builder.call(self.runtime["set_ret_tag"],
                                      [ir.Constant(i32, tag)])
                self.builder.ret(value)
            else:
                # For closure functions, store the tag before ret
                if (isinstance(expected, ir.IntType)
                        and self.function.name.startswith("fastpy.closure.")):
                    tag = self._infer_ret_tag_for_value(value, node.value)
                    self.builder.call(self.runtime["set_ret_tag"],
                                      [ir.Constant(i32, tag)])
                self.builder.ret(value)

    def _emit_scope_decref(self, exclude_var: str | None = None) -> None:
        """Emit decref for all FV-local variables in the current scope.
        Called before every function exit (return/implicit return).
        The `exclude_var` is the variable being returned (don't decref it —
        ownership transfers to the caller)."""
        if not self._USE_REFCOUNT:
            return
        for var_name, (alloca, tag) in self.variables.items():
            if var_name == exclude_var:
                continue
            if tag == "cell":
                continue  # cells are managed separately
            if var_name in self._global_vars:
                continue  # globals outlive the function
            if not (isinstance(alloca.type, ir.PointerType)
                    and alloca.type.pointee is fpy_val):
                continue  # not an FV local
            fv = self.builder.load(alloca, name=f"{var_name}.cleanup")
            fv_tag = self.builder.extract_value(fv, 0)
            fv_data = self.builder.extract_value(fv, 1)
            self.builder.call(self.runtime["rc_decref"], [fv_tag, fv_data])

    def _infer_ret_tag_for_value(self, value: ir.Value,
                                  node: ast.expr) -> int:
        """Infer the FpyValue tag for a bare LLVM value being returned.
        Used by closures to store the runtime tag in fpy_ret_tag."""
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1 or value.type.width == 32:
                return FPY_TAG_BOOL  # comparisons, bool ops
            # Check AST for bool-typed expressions
            if self._is_bool_typed(node):
                return FPY_TAG_BOOL
            return FPY_TAG_INT
        if isinstance(value.type, ir.DoubleType):
            return FPY_TAG_FLOAT
        if isinstance(value.type, ir.PointerType):
            if self._is_list_expr(node):
                return FPY_TAG_LIST
            if self._is_dict_expr(node):
                return FPY_TAG_DICT
            if self._is_obj_expr(node):
                return FPY_TAG_OBJ
            return FPY_TAG_STR
        return FPY_TAG_INT

    def _wrap_return_value(self, value: ir.Value, node: ast.AST) -> ir.Value:
        """Wrap a bare return value into an FpyValue, choosing the tag from
        the current function's static_ret_type if available, otherwise from
        the LLVM type of `value` itself."""
        # Use the static return type to decide tag (avoids mis-tagging strings
        # as ints when value came in as i8*, etc.)
        static_ret = None
        for info in self._user_functions.values():
            if info.func is self.function:
                static_ret = info.static_ret_type
                break
        # Match the static type: int → INT, float → FLOAT, ptr → STR by default
        # (caller's expected tag from static inference)
        if static_ret is double:
            if isinstance(value.type, ir.IntType):
                value = self.builder.sitofp(value, double)
            return self._fv_from_float(value)
        if static_ret is i8_ptr:
            # Pointer return — could be str, list, dict, tuple, obj.
            # Use the ret_tag to disambiguate.
            info = next((i for i in self._user_functions.values() if i.func is self.function), None)
            if info is not None:
                if info.ret_tag in ("ptr", "ptr:list"):
                    return self._fv_from_list(value)
                if info.ret_tag == "dict":
                    return self._fv_from_list(value)  # dicts stored as FpyList*
            # Default: treat as string
            if isinstance(value.type, ir.IntType):
                value = self.builder.inttoptr(value, i8_ptr)
            return self._fv_from_str(value)
        # Fallback: infer from LLVM type
        if isinstance(value.type, ir.IntType):
            if value.type.width == 64:
                return self._fv_from_int(value)
            # i32 bool
            return self._fv_from_bool(value)
        if isinstance(value.type, ir.DoubleType):
            return self._fv_from_float(value)
        if isinstance(value.type, ir.PointerType):
            return self._fv_from_str(value)
        raise CodeGenError(f"Cannot wrap return value of type {value.type} into FpyValue", node)

    def _infer_for_tuple_elem_types(self, iter_node: ast.expr, n: int) -> list[str]:
        """Given `for a,b in <iter>`, infer types of a and b from the first tuple.

        Returns list of "int" or "str" (default). If the iter is
        `enumerate(...)` we know the first is an int index.
        """
        types: list[str] = ["str"] * n
        # enumerate(x): first is int, second inherits x's element type
        if (isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name)
                and iter_node.func.id == "enumerate"):
            if n >= 1:
                types[0] = "int"
            if n >= 2 and iter_node.args:
                types[1] = self._infer_list_elem_type(iter_node.args[0])
            return types
        # zip(a, b): check each side's first element
        if (isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name)
                and iter_node.func.id == "zip"):
            for i, arg in enumerate(iter_node.args[:n]):
                types[i] = self._get_list_elem_type(arg)
            return types
        # sorted(d.items()) / d.items(): keys are strings, values inherit from dict
        items_call = None
        if (isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Attribute)
                and iter_node.func.attr == "items"):
            items_call = iter_node
        elif (isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name)
                and iter_node.func.id == "sorted" and iter_node.args
                and isinstance(iter_node.args[0], ast.Call)
                and isinstance(iter_node.args[0].func, ast.Attribute)
                and iter_node.args[0].func.attr == "items"):
            items_call = iter_node.args[0]
        if items_call is not None and n >= 2:
            types[0] = "str"
            dict_node = items_call.func.value
            if isinstance(dict_node, ast.Name):
                if dict_node.id in self._dict_var_int_values:
                    types[1] = "int"
                elif dict_node.id in self._dict_var_list_values:
                    types[1] = "list"
                else:
                    types[1] = "str"
            return types
        # Literal list of tuples: look at first tuple's elements
        list_node = iter_node
        if isinstance(iter_node, ast.Name):
            # Look up the variable's most recent list-of-tuples assignment in the function
            list_node = self._lookup_list_literal(iter_node.id)
        if isinstance(list_node, ast.List) and list_node.elts:
            first = list_node.elts[0]
            if isinstance(first, ast.Tuple):
                for i, el in enumerate(first.elts[:n]):
                    if isinstance(el, ast.Constant):
                        if isinstance(el.value, bool):
                            types[i] = "int"
                        elif isinstance(el.value, int):
                            types[i] = "int"
                        elif isinstance(el.value, str):
                            types[i] = "str"
        return types

    def _lookup_list_literal(self, name: str) -> ast.expr | None:
        """Look up the most recent assignment of a list literal to `name` in this scope."""
        stmts = getattr(self, "_current_scope_stmts", None)
        if stmts is None:
            return None
        for stmt in stmts:
            for sub in ast.walk(stmt):
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and isinstance(sub.targets[0], ast.Name)
                        and sub.targets[0].id == name
                        and isinstance(sub.value, ast.List)):
                    return sub.value
        return None

    def _emit_for_tuple_unpack(self, node: ast.For) -> None:
        """Emit for (k, v) in <list> or for i, (name, score) in enumerate(zip(...))."""
        targets = node.target.elts

        iter_val = self._emit_expr_value(node.iter)
        iter_len = self.builder.call(self.runtime["list_length"], [iter_val])

        # Unique per-loop index name so nested `for a,b in ...` loops
        # don't clobber each other's counter.
        self._block_counter += 1
        idx_name = f"__for_tup_idx_{self._block_counter}"
        self._store_variable(idx_name, ir.Constant(i64, 0), "int")

        cond_block = self._new_block("fort.cond")
        body_block = self._new_block("fort.body")
        incr_block = self._new_block("fort.incr")
        end_block = self._new_block("fort.end")

        self.builder.branch(cond_block)

        self.builder.position_at_end(cond_block)
        idx = self._load_variable(idx_name, node)
        cond = self.builder.icmp_signed("<", idx, iter_len)
        self.builder.cbranch(cond, body_block, end_block)

        self.builder.position_at_end(body_block)
        idx = self._load_variable(idx_name, node)
        # Iter elements are list/tuple pointers — fetch as bare i8*
        elem_list = self._list_get_as_bare(iter_val, idx, "list")

        # Determine inner element types from AST: first tuple's elements
        inner_types = self._infer_for_tuple_elem_types(node.iter, len(targets))

        # Unpack targets — handle both simple names and nested tuples
        for i, tgt in enumerate(targets):
            idx_const = ir.Constant(i64, i)
            if isinstance(tgt, ast.Name):
                elem_type = inner_types[i] if i < len(inner_types) else "str"
                # Use _fv_store_from_list so the runtime tag is preserved
                # (compile-time inference may be wrong for mixed-type tuples
                # like dict.items() returning (str, int) pairs).
                self._fv_store_from_list(tgt.id, elem_list, idx_const, elem_type)
            elif isinstance(tgt, ast.Tuple):
                # Nested tuple: get the sub-list and unpack it
                inner_list = self._list_get_as_bare(elem_list, idx_const, "list")
                for j, inner_tgt in enumerate(tgt.elts):
                    if isinstance(inner_tgt, ast.Name):
                        self._fv_store_from_list(
                            inner_tgt.id, inner_list, ir.Constant(i64, j), "str")
                    else:
                        raise CodeGenError("Deep nested tuple unpacking not supported", node)
            else:
                raise CodeGenError("Unsupported target in for tuple unpacking", node)

        self._loop_stack.append((end_block, incr_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(incr_block)

        self.builder.position_at_end(incr_block)
        idx = self._load_variable(idx_name, node)
        self._store_variable(idx_name, self.builder.add(idx, ir.Constant(i64, 1)), "int")
        self.builder.branch(cond_block)

        self.builder.position_at_end(end_block)

    def _emit_for_string(self, node: ast.For) -> None:
        """Emit for ch in string: iterate over characters."""
        var_name = node.target.id
        str_val = self._emit_expr_value(node.iter)
        str_len = self.builder.call(self.runtime["str_len"], [str_val])

        idx_name = f"__idx_str_{var_name}"
        self._store_variable(idx_name, ir.Constant(i64, 0), "int")

        cond_block = self._new_block("fors.cond")
        body_block = self._new_block("fors.body")
        incr_block = self._new_block("fors.incr")
        end_block = self._new_block("fors.end")

        self.builder.branch(cond_block)
        self.builder.position_at_end(cond_block)
        idx = self._load_variable(idx_name, node)
        cond = self.builder.icmp_signed("<", idx, str_len)
        self.builder.cbranch(cond, body_block, end_block)

        self.builder.position_at_end(body_block)
        idx = self._load_variable(idx_name, node)
        ch = self.builder.call(self.runtime["str_index"], [str_val, idx])
        self._store_variable(var_name, ch, "str")

        self._loop_stack.append((end_block, incr_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(incr_block)

        self.builder.position_at_end(incr_block)
        idx = self._load_variable(idx_name, node)
        self._store_variable(idx_name, self.builder.add(idx, ir.Constant(i64, 1)), "int")
        self.builder.branch(cond_block)

        self.builder.position_at_end(end_block)

    def _emit_for_iter_protocol(self, node: ast.For) -> None:
        """Emit `for x in obj` using __iter__/__next__ protocol.
        Calls obj.__iter__() to get the iterator, then repeatedly
        calls iterator.__next__() until StopIteration is raised."""
        var_name = node.target.id

        # Get the iterable and call __iter__()
        obj = self._emit_expr_value(node.iter)
        if isinstance(obj.type, ir.IntType):
            obj = self.builder.inttoptr(obj, i8_ptr)
        iter_name = self._make_string_constant("__iter__")
        iterator = self.builder.call(
            self.runtime["obj_call_method0"], [obj, iter_name])
        # iterator is i64 (result of method call) — convert to ptr
        iter_ptr = self.builder.inttoptr(iterator, i8_ptr)

        next_name = self._make_string_constant("__next__")

        cond_block = self._new_block("foriter.cond")
        body_block = self._new_block("foriter.body")
        else_block = self._new_block("foriter.else") if node.orelse else None
        end_block = self._new_block("foriter.end")

        self.builder.branch(cond_block)
        self.builder.position_at_end(cond_block)

        # Call __next__() — if StopIteration is raised, exit loop
        # We need to wrap in a try-like mechanism. Use exc_pending
        # after the call to detect StopIteration.
        result = self.builder.call(
            self.runtime["obj_call_method0"], [iter_ptr, next_name])
        pending = self.builder.call(self.runtime["exc_pending"], [])
        has_exc = self.builder.icmp_signed(
            "!=", pending, ir.Constant(i32, 0))
        after_loop = else_block if else_block else end_block
        self.builder.cbranch(has_exc, after_loop, body_block)

        self.builder.position_at_end(body_block)
        # Store the result as the loop variable
        self._store_variable(var_name, result, "int")

        self._loop_stack.append((end_block, cond_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        if else_block:
            self.builder.position_at_end(else_block)
            # Clear the StopIteration exception
            self.builder.call(self.runtime["exc_clear"], [])
            self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)
        # Clear StopIteration if still pending
        self.builder.call(self.runtime["exc_clear"], [])

    def _emit_for_list(self, node: ast.For) -> None:
        """Emit for x in <list>: iterate over list elements by index."""
        var_name = node.target.id

        # Evaluate the list
        list_val = self._emit_expr_value(node.iter)
        list_len = self.builder.call(self.runtime["list_length"], [list_val])

        # Index variable
        idx_name = f"__idx_{var_name}"
        self._store_variable(idx_name, ir.Constant(i64, 0), "int")

        cond_block = self._new_block("forl.cond")
        body_block = self._new_block("forl.body")
        incr_block = self._new_block("forl.incr")
        else_block = self._new_block("forl.else") if node.orelse else None
        end_block = self._new_block("forl.end")

        self.builder.branch(cond_block)

        self.builder.position_at_end(cond_block)
        idx = self._load_variable(idx_name, node)
        cond = self.builder.icmp_signed("<", idx, list_len)
        after_loop = else_block if else_block else end_block
        self.builder.cbranch(cond, body_block, after_loop)

        self.builder.position_at_end(body_block)
        # Get element via FV-ABI getter; store into the loop variable's FV
        # alloca directly, bypassing the unwrap-then-rewrap round-trip.
        idx = self._load_variable(idx_name, node)
        elem_type = self._get_list_elem_type(node.iter)
        # Determine the variable's tag from the list's element type
        if elem_type == "obj":
            var_tag = "obj"
        elif elem_type == "str":
            var_tag = "str"
        elif elem_type == "list":
            var_tag = "list:int"
        elif elem_type == "dict":
            var_tag = "dict"
        elif elem_type == "tuple":
            var_tag = "tuple"
        elif elem_type == "float":
            var_tag = "float"
        else:
            var_tag = "int"
        self._fv_store_from_list(var_name, list_val, idx, var_tag)

        # Mixed-value dict support for `for p in list_of_dicts:`. Build a
        # per-key type map so `p["age"]` (int) and `p["name"]` (str) in
        # the loop body use the right unwrap path.
        if elem_type == "dict":
            key_types = self._infer_list_of_dicts_key_types(node.iter)
            if key_types:
                self._dict_var_key_types[var_name] = key_types

        self._loop_stack.append((end_block, incr_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(incr_block)

        self.builder.position_at_end(incr_block)
        idx = self._load_variable(idx_name, node)
        incremented = self.builder.add(idx, ir.Constant(i64, 1))
        self._store_variable(idx_name, incremented, "int")
        self.builder.branch(cond_block)

        if else_block:
            self.builder.position_at_end(else_block)
            self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)

    def _emit_for_dict(self, node: ast.For) -> None:
        """Emit for k in <dict>: iterate over dict's keys."""
        var_name = node.target.id

        # Call dict_keys to get a list of keys, then iterate as a string list
        dict_val = self._emit_expr_value(node.iter)
        keys_list = self.builder.call(self.runtime["dict_keys"], [dict_val])
        list_len = self.builder.call(self.runtime["list_length"], [keys_list])

        idx_name = f"__idx_{var_name}"
        self._store_variable(idx_name, ir.Constant(i64, 0), "int")

        cond_block = self._new_block("ford.cond")
        body_block = self._new_block("ford.body")
        incr_block = self._new_block("ford.incr")
        else_block = self._new_block("ford.else") if node.orelse else None
        end_block = self._new_block("ford.end")

        self.builder.branch(cond_block)

        self.builder.position_at_end(cond_block)
        idx = self._load_variable(idx_name, node)
        cond = self.builder.icmp_signed("<", idx, list_len)
        after_loop = else_block if else_block else end_block
        self.builder.cbranch(cond, body_block, after_loop)

        self.builder.position_at_end(body_block)
        idx = self._load_variable(idx_name, node)
        # Keys are strings
        self._fv_store_from_list(var_name, keys_list, idx, "str")

        self._loop_stack.append((end_block, incr_block))
        self._emit_stmts(node.body)
        self._loop_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(incr_block)

        self.builder.position_at_end(incr_block)
        idx = self._load_variable(idx_name, node)
        incremented = self.builder.add(idx, ir.Constant(i64, 1))
        self._store_variable(idx_name, incremented, "int")
        self.builder.branch(cond_block)

        if else_block:
            self.builder.position_at_end(else_block)
            self._emit_stmts(node.orelse)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_block)

        self.builder.position_at_end(end_block)

    def _emit_break(self, node: ast.Break) -> None:
        if not self._loop_stack:
            raise CodeGenError("'break' outside loop", node)
        end_block, _ = self._loop_stack[-1]
        self.builder.branch(end_block)

    def _emit_continue(self, node: ast.Continue) -> None:
        if not self._loop_stack:
            raise CodeGenError("'continue' outside loop", node)
        _, continue_block = self._loop_stack[-1]
        self.builder.branch(continue_block)

    # -----------------------------------------------------------------
    # Conditions and comparisons
    # -----------------------------------------------------------------

    def _emit_condition(self, node: ast.expr) -> ir.Value:
        """Emit an expression as a boolean condition (i1)."""
        if isinstance(node, ast.Compare):
            return self._emit_compare(node)
        elif isinstance(node, ast.BoolOp):
            # BoolOp returns the operand value; convert to truthiness here
            val = self._emit_boolop(node)
            return self._truthiness(val)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            cond = self._emit_condition(node.operand)
            return self.builder.not_(cond)
        elif isinstance(node, ast.Constant):
            # Constant used as condition: if True, if False, if 0, etc.
            val = bool(node.value)
            return ir.Constant(ir.IntType(1), 1 if val else 0)
        elif isinstance(node, ast.Name):
            # Variable used as condition: truthy check (type-aware for lists/dicts/strings)
            if node.id in self.variables:
                _, tag = self.variables[node.id]
                if tag.startswith("list") or tag == "dict" or tag == "str":
                    return self._truthiness_of_expr(node)
            value = self._load_variable(node.id, node)
            return self._truthiness(value)
        else:
            # General expression: evaluate and check truthiness
            return self._truthiness_of_expr(node)

    def _truthiness(self, value: ir.Value) -> ir.Value:
        """Convert an LLVM value to a boolean (i1) via Python truthiness.

        For pointer values, this checks non-null — NOT emptiness. Callers that
        know the value is a string/list/dict should use a length check instead
        (see `_truthiness_of_expr`).
        """
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                return value
            return self.builder.icmp_signed("!=", value, ir.Constant(value.type, 0))
        elif isinstance(value.type, ir.DoubleType):
            return self.builder.fcmp_ordered("!=", value, ir.Constant(double, 0.0))
        elif isinstance(value.type, ir.PointerType):
            null_ptr = ir.Constant(value.type, None)
            return self.builder.icmp_unsigned("!=", value, null_ptr)
        else:
            return ir.Constant(ir.IntType(1), 0)

    def _truthiness_of_expr(self, node: ast.expr) -> ir.Value:
        """Type-aware truthiness: empty str/list/dict → False, else non-null.

        For Name nodes backed by an FV alloca and dict/list subscripts,
        dispatch through `fv_truthy` which handles every tag at runtime.
        AST-level checks remain for cases where we know the type at
        compile time (literals, function returns) and can avoid the FV
        round-trip.
        """
        # FV-backed variables: dispatch via runtime tag, no AST guessing
        if (self._USE_FV_LOCALS and isinstance(node, ast.Name)
                and node.id in self.variables
                and node.id not in self._global_vars):
            alloca, type_tag = self.variables[node.id]
            if (type_tag != "cell"
                    and isinstance(alloca.type, ir.PointerType)
                    and alloca.type.pointee is fpy_val):
                fv = self.builder.load(alloca, name=f"{node.id}.fv")
                return self._fv_call_truthy(fv)
        # Dict/list subscript: dispatch via runtime tag from FV getter
        if (isinstance(node, ast.Subscript)
                and not isinstance(node.slice, ast.Slice)
                and (self._is_dict_expr(node.value) or self._is_list_expr(node.value))):
            fv = self._load_or_wrap_fv(node)
            return self._fv_call_truthy(fv)
        # Object attribute: dispatch via runtime tag from obj_get_fv
        if (isinstance(node, ast.Attribute)
                and not (isinstance(node.value, ast.Name)
                         and node.value.id in self._user_classes)):
            fv = self._load_or_wrap_fv(node)
            if fv.type is fpy_val:
                return self._fv_call_truthy(fv)
        if self._is_list_expr(node):
            val = self._emit_expr_value(node)
            length = self.builder.call(self.runtime["list_length"], [val])
            return self.builder.icmp_signed("!=", length, ir.Constant(i64, 0))
        if self._is_dict_expr(node):
            val = self._emit_expr_value(node)
            length = self.builder.call(self.runtime["dict_length"], [val])
            return self.builder.icmp_signed("!=", length, ir.Constant(i64, 0))
        # __bool__ on user-class objects
        if self._is_obj_expr(node):
            obj_cls = self._infer_object_class(node)
            if obj_cls and self._class_has_method(obj_cls, "__bool__"):
                obj = self._emit_expr_value(node)
                if isinstance(obj.type, ir.IntType):
                    obj = self.builder.inttoptr(obj, i8_ptr)
                name_ptr = self._make_string_constant("__bool__")
                result = self.builder.call(
                    self.runtime["obj_call_method0"], [obj, name_ptr])
                return self.builder.icmp_signed(
                    "!=", result, ir.Constant(i64, 0))
        val = self._emit_expr_value(node)
        if isinstance(val.type, ir.PointerType):
            # Strings: empty string → False
            null_ptr = ir.Constant(val.type, None)
            is_non_null = self.builder.icmp_unsigned("!=", val, null_ptr)
            length = self.builder.call(self.runtime["str_len"], [val])
            has_len = self.builder.icmp_signed("!=", length, ir.Constant(i64, 0))
            return self.builder.and_(is_non_null, has_len)
        return self._truthiness(val)

    def _emit_compare(self, node: ast.Compare) -> ir.Value:
        """Emit a comparison expression. Handles chained comparisons."""
        left = self._emit_expr_value(node.left)
        result = None

        for op, comparator_node in zip(node.ops, node.comparators):
            # Handle `is`/`is not` specially (identity comparison)
            if isinstance(op, (ast.Is, ast.IsNot)):
                cmp = self._emit_is_compare(op, node.left, comparator_node, node)
            # Handle `in`/`not in` specially
            elif isinstance(op, (ast.In, ast.NotIn)):
                cmp = self._emit_in_compare(op, left, comparator_node, node)
            else:
                right = self._emit_expr_value(comparator_node)
                cmp_left, cmp_right = left, right
                # Object comparison: dispatch to __eq__
                if (isinstance(op, ast.Eq)
                        and isinstance(cmp_left.type, ir.PointerType)
                        and isinstance(cmp_right.type, ir.PointerType)
                        and self._is_obj_expr(node.left)):
                    method_name = self._make_string_constant("__eq__")
                    right_as_i64 = self.builder.ptrtoint(cmp_right, i64)
                    result_i64 = self.builder.call(
                        self.runtime["obj_call_method1"],
                        [cmp_left, method_name, right_as_i64])
                    cmp = self.builder.icmp_signed("!=", result_i64, ir.Constant(i64, 0))
                elif (isinstance(cmp_left.type, ir.PointerType)
                        and isinstance(cmp_right.type, ir.PointerType)
                        and isinstance(op, (ast.Eq, ast.NotEq))
                        and (self._is_list_expr(node.left)
                             or self._is_tuple_expr(node.left))):
                    # List/tuple equality
                    eq_result = self.builder.call(self.runtime["list_equal"], [cmp_left, cmp_right])
                    truthy = self.builder.icmp_signed("!=", eq_result, ir.Constant(i32, 0))
                    if isinstance(op, ast.NotEq):
                        truthy = self.builder.not_(truthy)
                    cmp = truthy
                elif (isinstance(cmp_left.type, ir.PointerType)
                        and isinstance(cmp_right.type, ir.PointerType)
                        and isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                        and (self._is_list_expr(node.left)
                             or self._is_tuple_expr(node.left))):
                    # List/tuple lexicographic comparison — returns -1/0/1.
                    cmp_result = self.builder.call(
                        self.runtime["list_compare"], [cmp_left, cmp_right])
                    zero = ir.Constant(i64, 0)
                    if isinstance(op, ast.Lt):
                        cmp = self.builder.icmp_signed("<", cmp_result, zero)
                    elif isinstance(op, ast.LtE):
                        cmp = self.builder.icmp_signed("<=", cmp_result, zero)
                    elif isinstance(op, ast.Gt):
                        cmp = self.builder.icmp_signed(">", cmp_result, zero)
                    else:  # ast.GtE
                        cmp = self.builder.icmp_signed(">=", cmp_result, zero)
                elif (isinstance(cmp_left.type, ir.PointerType)
                        and isinstance(cmp_right.type, ir.PointerType)
                        and isinstance(op, (ast.Eq, ast.NotEq))):
                    # String comparison
                    cmp_result = self.builder.call(self.runtime["str_compare"], [cmp_left, cmp_right])
                    if isinstance(op, ast.Eq):
                        cmp = self.builder.icmp_signed("==", cmp_result, ir.Constant(i64, 0))
                    else:
                        cmp = self.builder.icmp_signed("!=", cmp_result, ir.Constant(i64, 0))
                elif isinstance(cmp_left.type, ir.DoubleType) or isinstance(cmp_right.type, ir.DoubleType):
                    if isinstance(cmp_left.type, ir.IntType):
                        cmp_left = self.builder.sitofp(cmp_left, double)
                    if isinstance(cmp_right.type, ir.IntType):
                        cmp_right = self.builder.sitofp(cmp_right, double)
                    cmp = self._emit_float_compare(op, cmp_left, cmp_right, node)
                else:
                    cmp = self._emit_int_compare(op, cmp_left, cmp_right, node)
                left = right

            if result is None:
                result = cmp
            else:
                result = self.builder.and_(result, cmp)

        return result

    def _emit_is_compare(self, op, left_node, right_node, node) -> ir.Value:
        """Emit `is` / `is not` comparison. Supports None and Ellipsis."""
        # Check if comparing to None
        is_none_check = (
            (isinstance(left_node, ast.Constant) and left_node.value is None) or
            (isinstance(right_node, ast.Constant) and right_node.value is None)
        )
        # Check if comparing to Ellipsis
        is_ellipsis = (
            (isinstance(left_node, ast.Constant) and left_node.value is ...) or
            (isinstance(right_node, ast.Constant) and right_node.value is ...)
        )
        # For `x is True` / `x is False` — use value comparison
        is_bool_check = (
            (isinstance(left_node, ast.Constant) and isinstance(left_node.value, bool)) or
            (isinstance(right_node, ast.Constant) and isinstance(right_node.value, bool))
        )
        if is_ellipsis:
            # Ellipsis is a singleton — `x is ...` is always True if x was
            # assigned `...`, but we represent ... as i64(0). For now, just
            # compare values (both ... are i64(0)).
            left = self._emit_expr_value(left_node)
            right = self._emit_expr_value(right_node)
            if isinstance(op, ast.IsNot):
                return self.builder.icmp_signed("!=", left, right)
            return self.builder.icmp_signed("==", left, right)
        if is_bool_check and not is_none_check:
            left = self._emit_expr_value(left_node)
            right = self._emit_expr_value(right_node)
            if isinstance(op, ast.IsNot):
                return self.builder.icmp_signed("!=", left, right)
            return self.builder.icmp_signed("==", left, right)
        if not is_none_check:
            raise CodeGenError("'is' only supported for None/Ellipsis comparisons", node)
        # Determine if the non-None side is statically known to be None
        other = left_node if isinstance(right_node, ast.Constant) and right_node.value is None else right_node

        # For FV-backed variables, compare the runtime tag with FPY_TAG_NONE.
        # This handles functions that return None on some paths but not others.
        if (self._USE_FV_LOCALS and isinstance(other, ast.Name)
                and other.id in self.variables
                and other.id not in self._global_vars):
            alloca, _ = self.variables[other.id]
            if (isinstance(alloca.type, ir.PointerType)
                    and alloca.type.pointee is fpy_val):
                fv = self.builder.load(alloca, name=f"{other.id}.fv.isnone")
                tag = self.builder.extract_value(fv, 0, name="is_none.tag")
                if isinstance(op, ast.IsNot):
                    return self.builder.icmp_signed(
                        "!=", tag, ir.Constant(i32, FPY_TAG_NONE))
                return self.builder.icmp_signed(
                    "==", tag, ir.Constant(i32, FPY_TAG_NONE))

        # For Attribute expressions on objects (e.g. `obj.attr is None`),
        # load the full FV via slot read and check the runtime tag. The
        # data-only path in _emit_attr_load would lose the NONE tag.
        if (self._USE_FV_LOCALS
                and isinstance(other, ast.Attribute)
                and self._is_obj_expr(other.value)):
            fv = self._load_or_wrap_fv(other)
            tag = self.builder.extract_value(fv, 0, name="is_none.tag")
            if isinstance(op, ast.IsNot):
                return self.builder.icmp_signed(
                    "!=", tag, ir.Constant(i32, FPY_TAG_NONE))
            return self.builder.icmp_signed(
                "==", tag, ir.Constant(i32, FPY_TAG_NONE))

        # For Call expressions on user functions that may return None
        # (e.g. `func(x) is None`), call via FV path to get the runtime
        # tag.  Without this, the unwrapped return loses the NONE tag.
        if (self._USE_FV_LOCALS
                and isinstance(other, ast.Call)
                and isinstance(other.func, ast.Name)
                and other.func.id in self._user_functions):
            info = self._user_functions[other.func.id]
            if info.uses_fv_abi and info.may_return_none:
                fv = self._emit_user_call_fv(other)
                tag = self.builder.extract_value(fv, 0, name="is_none.tag")
                if isinstance(op, ast.IsNot):
                    return self.builder.icmp_signed(
                        "!=", tag, ir.Constant(i32, FPY_TAG_NONE))
                return self.builder.icmp_signed(
                    "==", tag, ir.Constant(i32, FPY_TAG_NONE))

        is_other_none = False
        if isinstance(other, ast.Constant) and other.value is None:
            is_other_none = True
        elif isinstance(other, ast.Name) and other.id in self.variables:
            _, tag = self.variables[other.id]
            if tag == "none":
                is_other_none = True
        val = 1 if is_other_none else 0
        if isinstance(op, ast.IsNot):
            val = 1 - val
        return ir.Constant(ir.IntType(1), val)

    def _emit_in_compare(self, op, left_val, container_node, node) -> ir.Value:
        """Emit `in` / `not in` comparison."""
        # For sets: O(1) hash lookup via dict-backed set
        if self._is_set_expr(container_node):
            container = self._emit_expr_value(container_node)
            if isinstance(container.type, ir.IntType):
                container = self.builder.inttoptr(container, i8_ptr)
            tag, data = self._bare_to_tag_data(left_val, None)
            result = self.builder.call(
                self.runtime["set_contains_fv"],
                [container, ir.Constant(i32, tag), data])
            result = self.builder.trunc(result, ir.IntType(1))
            if isinstance(op, ast.NotIn):
                result = self.builder.not_(result)
            return result
        # For list/tuple: iterate and compare
        if (self._is_list_expr(container_node) or self._is_tuple_expr(container_node)
                or isinstance(container_node, (ast.List, ast.Tuple))):
            container = self._emit_expr_value(container_node)
            length = self.builder.call(self.runtime["list_length"], [container])

            # Linear search
            result_alloca = self.builder.alloca(ir.IntType(1), name="in.result")
            self.builder.store(ir.Constant(ir.IntType(1), 0), result_alloca)

            idx_alloca = self.builder.alloca(i64, name="in.idx")
            self.builder.store(ir.Constant(i64, 0), idx_alloca)

            cond_block = self._new_block("in.cond")
            body_block = self._new_block("in.body")
            end_block = self._new_block("in.end")

            self.builder.branch(cond_block)

            self.builder.position_at_end(cond_block)
            idx = self.builder.load(idx_alloca)
            cond = self.builder.icmp_signed("<", idx, length)
            self.builder.cbranch(cond, body_block, end_block)

            self.builder.position_at_end(body_block)
            idx = self.builder.load(idx_alloca)
            # Use the FV getter once; unwrap based on the static elem_type
            elem_type = self._get_list_elem_type(container_node)
            if elem_type == "str" or isinstance(left_val.type, ir.PointerType):
                elem = self._list_get_as_bare(container, idx, "str")
                cmp_result = self.builder.call(self.runtime["str_compare"], [left_val, elem])
                eq = self.builder.icmp_signed("==", cmp_result, ir.Constant(i64, 0))
            elif elem_type == "float" or isinstance(left_val.type, ir.DoubleType):
                elem = self._list_get_as_bare(container, idx, "float")
                cmp_left = left_val
                if isinstance(cmp_left.type, ir.IntType):
                    cmp_left = self.builder.sitofp(cmp_left, double)
                eq = self.builder.fcmp_ordered("==", cmp_left, elem)
            else:
                elem = self._list_get_as_bare(container, idx, "int")
                eq = self.builder.icmp_signed("==", left_val, elem)
            found_block = self._new_block("in.found")
            next_block = self._new_block("in.next")
            self.builder.cbranch(eq, found_block, next_block)

            self.builder.position_at_end(found_block)
            self.builder.store(ir.Constant(ir.IntType(1), 1), result_alloca)
            self.builder.branch(end_block)

            self.builder.position_at_end(next_block)
            idx = self.builder.load(idx_alloca)
            self.builder.store(self.builder.add(idx, ir.Constant(i64, 1)), idx_alloca)
            self.builder.branch(cond_block)

            self.builder.position_at_end(end_block)
            result = self.builder.load(result_alloca)
            if isinstance(op, ast.NotIn):
                result = self.builder.not_(result)
            return result

        # Dict 'in': "key" in dict
        if self._is_dict_expr(container_node):
            container = self._emit_expr_value(container_node)
            # Int keys use the int-keyed has-check (stored natively).
            if isinstance(left_val.type, ir.IntType):
                result = self.builder.call(
                    self.runtime["dict_has_int_key"], [container, left_val])
            else:
                if not isinstance(left_val.type, ir.PointerType):
                    left_val = self.builder.inttoptr(left_val, i8_ptr)
                result = self.builder.call(
                    self.runtime["dict_has_key"], [container, left_val])
            result_i1 = self.builder.icmp_signed("!=", result, ir.Constant(i32, 0))
            if isinstance(op, ast.NotIn):
                result_i1 = self.builder.not_(result_i1)
            return result_i1

        # String 'in': "x" in "hello"
        container = self._emit_expr_value(container_node)
        if isinstance(container.type, ir.PointerType) and isinstance(left_val.type, ir.PointerType):
            result = self.builder.call(self.runtime["str_contains"], [container, left_val])
            result_i1 = self.builder.icmp_signed("!=", result, ir.Constant(i32, 0))
            if isinstance(op, ast.NotIn):
                result_i1 = self.builder.not_(result_i1)
            return result_i1

        # __contains__ on user-class objects
        if self._is_obj_expr(container_node):
            obj_cls = self._infer_object_class(container_node)
            if obj_cls and self._class_has_method(obj_cls, "__contains__"):
                container = self._emit_expr_value(container_node)
                if isinstance(container.type, ir.IntType):
                    container = self.builder.inttoptr(container, i8_ptr)
                if isinstance(left_val.type, ir.PointerType):
                    arg = self.builder.ptrtoint(left_val, i64)
                elif isinstance(left_val.type, ir.DoubleType):
                    arg = self.builder.bitcast(left_val, i64)
                elif isinstance(left_val.type, ir.IntType) and left_val.type.width != 64:
                    arg = self.builder.zext(left_val, i64)
                else:
                    arg = left_val
                name_ptr = self._make_string_constant("__contains__")
                result = self.builder.call(
                    self.runtime["obj_call_method1"],
                    [container, name_ptr, arg])
                result_i1 = self.builder.icmp_signed(
                    "!=", result, ir.Constant(i64, 0))
                if isinstance(op, ast.NotIn):
                    result_i1 = self.builder.not_(result_i1)
                return result_i1

        # pyobj-tagged container: route through CPython bridge
        if (isinstance(container_node, ast.Name)
                and container_node.id in self.variables
                and self.variables[container_node.id][1] == "pyobj"):
            container = self._load_variable(container_node.id, container_node)
            if isinstance(container.type, ir.IntType):
                container = self.builder.inttoptr(container, i8_ptr)
            # Use CPython's __contains__ via bridge
            contains_name = self._make_string_constant("__contains__")
            method = self.builder.call(
                self.runtime["cpython_getattr"], [container, contains_name])
            tag, data = self._bare_to_tag_data(left_val, None)
            out_tag = self._create_entry_alloca(i32, "pyin.tag")
            out_data = self._create_entry_alloca(i64, "pyin.data")
            self.builder.call(self.runtime["cpython_call1"],
                              [method, ir.Constant(i32, tag), data,
                               out_tag, out_data])
            result = self.builder.load(out_data)
            result_i1 = self.builder.icmp_signed(
                "!=", result, ir.Constant(i64, 0))
            if isinstance(op, ast.NotIn):
                result_i1 = self.builder.not_(result_i1)
            return result_i1

        raise CodeGenError("'in' operator not supported for this type", node)

    def _emit_int_compare(
        self, op: ast.cmpop, left: ir.Value, right: ir.Value, node: ast.AST
    ) -> ir.Value:
        ops = {
            ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            ast.Eq: "==", ast.NotEq: "!=",
        }
        op_str = ops.get(type(op))
        if op_str is None:
            raise CodeGenError(f"Unsupported comparison: {type(op).__name__}", node)
        return self.builder.icmp_signed(op_str, left, right)

    def _emit_float_compare(
        self, op: ast.cmpop, left: ir.Value, right: ir.Value, node: ast.AST
    ) -> ir.Value:
        ops = {
            ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            ast.Eq: "==", ast.NotEq: "!=",
        }
        op_str = ops.get(type(op))
        if op_str is None:
            raise CodeGenError(f"Unsupported comparison: {type(op).__name__}", node)
        return self.builder.fcmp_ordered(op_str, left, right)

    def _emit_boolop(self, node: ast.BoolOp) -> ir.Value:
        """Emit short-circuit boolean operations (and, or)."""
        if isinstance(node.op, ast.And):
            return self._emit_short_circuit_and(node.values)
        elif isinstance(node.op, ast.Or):
            return self._emit_short_circuit_or(node.values)
        else:
            raise CodeGenError(f"Unsupported bool op: {type(node.op).__name__}", node)

    def _emit_short_circuit_and(self, values: list[ast.expr]) -> ir.Value:
        """Emit short-circuit AND — returns the operand value, not a bool.

        Python: `a and b` returns `a` if `a` is falsy, else `b`.
        """
        # Determine the common result type from all operands
        result_type = self._common_boolop_type(values)
        result_alloca = self._create_entry_alloca(result_type, "and.result")
        merge_block = self._new_block("and.end")

        for i, val_node in enumerate(values):
            val = self._emit_expr_value(val_node)
            val = self._coerce_to_type(val, result_type)
            self.builder.store(val, result_alloca)
            if i < len(values) - 1:
                truthy = self._value_truthiness(val)
                next_block = self._new_block("and.next")
                # If truthy, continue; else short-circuit with current value
                self.builder.cbranch(truthy, next_block, merge_block)
                self.builder.position_at_end(next_block)
            else:
                self.builder.branch(merge_block)

        self.builder.position_at_end(merge_block)
        return self.builder.load(result_alloca)

    def _emit_short_circuit_or(self, values: list[ast.expr]) -> ir.Value:
        """Emit short-circuit OR — returns the operand value, not a bool.

        Python: `a or b` returns `a` if `a` is truthy, else `b`.
        """
        result_type = self._common_boolop_type(values)
        result_alloca = self._create_entry_alloca(result_type, "or.result")
        merge_block = self._new_block("or.end")

        for i, val_node in enumerate(values):
            val = self._emit_expr_value(val_node)
            val = self._coerce_to_type(val, result_type)
            self.builder.store(val, result_alloca)
            if i < len(values) - 1:
                truthy = self._value_truthiness(val)
                next_block = self._new_block("or.next")
                # If truthy, short-circuit; else continue
                self.builder.cbranch(truthy, merge_block, next_block)
                self.builder.position_at_end(next_block)
            else:
                self.builder.branch(merge_block)

        self.builder.position_at_end(merge_block)
        return self.builder.load(result_alloca)

    def _common_boolop_type(self, values: list[ast.expr]) -> ir.Type:
        """Determine a common LLVM type for boolop operands."""
        has_str = False
        has_float = False
        has_int = False
        has_non_bool = False
        for v in values:
            if isinstance(v, ast.Constant):
                if isinstance(v.value, bool):
                    pass  # bool only — keep as i32
                elif isinstance(v.value, str):
                    has_str = True
                    has_non_bool = True
                elif isinstance(v.value, float):
                    has_float = True
                    has_non_bool = True
                elif isinstance(v.value, int):
                    has_int = True
                    has_non_bool = True
            elif isinstance(v, ast.Name) and v.id in self.variables:
                _, tag = self.variables[v.id]
                has_non_bool = True
                if tag == "str":
                    has_str = True
                elif tag == "float":
                    has_float = True
                elif tag.startswith("list") or tag == "dict":
                    has_str = True  # pointer type
                else:
                    has_int = True
            elif isinstance(v, ast.JoinedStr):
                has_str = True
                has_non_bool = True
            elif isinstance(v, ast.Compare):
                pass  # comparison returns bool
            else:
                has_int = True
                has_non_bool = True
        # If all operands are bool, keep i32 so prints as True/False
        if not has_non_bool:
            return i32
        if has_str:
            return i8_ptr
        if has_float:
            return double
        return i64

    def _coerce_to_type(self, value: ir.Value, target_type: ir.Type) -> ir.Value:
        """Coerce a value to target_type for boolop result unification."""
        if value.type == target_type:
            return value
        if isinstance(target_type, ir.IntType) and target_type.width == 64:
            if isinstance(value.type, ir.IntType) and value.type.width < 64:
                return self.builder.zext(value, i64)
            if isinstance(value.type, ir.DoubleType):
                return self.builder.fptosi(value, i64)
            if isinstance(value.type, ir.PointerType):
                return self.builder.ptrtoint(value, i64)
        if isinstance(target_type, ir.IntType) and target_type.width == 32:
            if isinstance(value.type, ir.IntType):
                if value.type.width < 32:
                    return self.builder.zext(value, i32)
                if value.type.width > 32:
                    return self.builder.trunc(value, i32)
        if isinstance(target_type, ir.DoubleType):
            if isinstance(value.type, ir.IntType):
                return self.builder.sitofp(value, double)
        if isinstance(target_type, ir.PointerType):
            if isinstance(value.type, ir.IntType):
                # Convert int to string for string-typed boolop results
                return self.builder.call(self.runtime["int_to_str"], [value])
            if isinstance(value.type, ir.DoubleType):
                return self.builder.call(self.runtime["float_to_str"], [value])
        return value

    def _value_truthiness(self, value: ir.Value) -> ir.Value:
        """Return i1 indicating whether the value is truthy."""
        if isinstance(value.type, ir.IntType):
            return self.builder.icmp_signed("!=", value, ir.Constant(value.type, 0))
        if isinstance(value.type, ir.DoubleType):
            return self.builder.fcmp_ordered("!=", value, ir.Constant(double, 0.0))
        if isinstance(value.type, ir.PointerType):
            # Empty string is falsy; also check non-null pointer
            length = self.builder.call(self.runtime["str_len"], [value])
            return self.builder.icmp_signed("!=", length, ir.Constant(i64, 0))
        return ir.Constant(ir.IntType(1), 0)

    def _emit_call(self, node: ast.Call) -> None:
        """Emit a function call (as a statement — discard return value)."""
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "print":
                self._emit_print(node)
                return
            # Check if it's a closure variable
            if name in self.variables:
                _, tag = self.variables[name]
                if tag == "closure":
                    self._emit_closure_call(node)
                    return
            if name in self._user_functions:
                self._emit_user_call(node)
                return
            if name in self._user_classes:
                self._emit_constructor(node)
                return
        if isinstance(node.func, ast.Attribute):
            # Check if receiver is a CPython module/object (pyobj-tagged)
            # Also handle chained attrs: os.path.exists() → os is pyobj
            receiver_is_pyobj = False
            if (isinstance(node.func.value, ast.Name)
                    and node.func.value.id in self.variables
                    and self.variables[node.func.value.id][1] == "pyobj"):
                receiver_is_pyobj = True
            elif (isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id in self.variables
                    and self.variables[node.func.value.value.id][1] == "pyobj"):
                receiver_is_pyobj = True
            if receiver_is_pyobj:
                self._emit_cpython_method_call(node)
                return
            self._emit_method_call(node)
            return
        # Check for direct pyobj call: func(args) where func is pyobj-tagged
        if (isinstance(node.func, ast.Name)
                and node.func.id in self.variables
                and self.variables[node.func.id][1] == "pyobj"):
            self._emit_cpython_direct_call(node)
            return
        # Last resort: try as closure call
        if isinstance(node.func, ast.Name) and node.func.id in self.variables:
            self._emit_closure_call(node)
            return
        # CPython bridge fallback for builtin calls used as statements
        # (e.g. next(gen), iter(x), etc.)
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if (name not in self._user_functions
                    and name not in self._user_classes
                    and name not in self.variables):
                builtin_name = self._make_string_constant("builtins")
                builtins_mod = self.builder.call(
                    self.runtime["cpython_import"], [builtin_name])
                func_name = self._make_string_constant(name)
                callable_ptr = self.builder.call(
                    self.runtime["cpython_getattr"],
                    [builtins_mod, func_name])
                out_tag = self._create_entry_alloca(i32, "pyblt.tag")
                out_data = self._create_entry_alloca(i64, "pyblt.data")
                n_args = len(node.args)
                if n_args == 0:
                    self.builder.call(self.runtime["cpython_call0"],
                                      [callable_ptr, out_tag, out_data])
                elif n_args == 1:
                    arg = self._emit_expr_value(node.args[0])
                    tag, data = self._bare_to_tag_data(arg, node.args[0])
                    self.builder.call(self.runtime["cpython_call1"],
                                      [callable_ptr,
                                       ir.Constant(i32, tag), data,
                                       out_tag, out_data])
                elif n_args == 2:
                    a1 = self._emit_expr_value(node.args[0])
                    t1, d1 = self._bare_to_tag_data(a1, node.args[0])
                    a2 = self._emit_expr_value(node.args[1])
                    t2, d2 = self._bare_to_tag_data(a2, node.args[1])
                    self.builder.call(self.runtime["cpython_call2"],
                                      [callable_ptr,
                                       ir.Constant(i32, t1), d1,
                                       ir.Constant(i32, t2), d2,
                                       out_tag, out_data])
                return
        raise CodeGenError(f"Unsupported function call: {ast.dump(node.func)}", node)

    def _emit_closure_call(self, node: ast.Call) -> ir.Value:
        """Call a closure or function-pointer variable."""
        name = node.func.id
        val = self._load_variable(name, node)
        n_args = len(node.args)

        # Special case: cls() inside a classmethod constructs an instance.
        # The cls parameter is an i32 class_id; call obj_new directly.
        if name == "cls" and isinstance(val.type, ir.IntType) and val.type.width == 32:
            obj = self.builder.call(self.runtime["obj_new"], [val])
            # Call __init__ via runtime dispatch
            init_args = []
            for arg_node in node.args:
                v = self._emit_expr_value(arg_node)
                if isinstance(v.type, ir.PointerType):
                    v = self.builder.ptrtoint(v, i64)
                init_args.append(v)
            n_init = len(init_args)
            if n_init == 0:
                self.builder.call(self.runtime["obj_call_init0"], [obj])
            elif n_init == 1:
                self.builder.call(self.runtime["obj_call_init1"], [obj, init_args[0]])
            elif n_init == 2:
                self.builder.call(self.runtime["obj_call_init2"], [obj, init_args[0], init_args[1]])
            elif n_init == 3:
                self.builder.call(self.runtime["obj_call_init3"],
                                  [obj, init_args[0], init_args[1], init_args[2]])
            elif n_init == 4:
                self.builder.call(self.runtime["obj_call_init4"],
                                  [obj, init_args[0], init_args[1], init_args[2], init_args[3]])
            else:
                raise CodeGenError(f"cls() with {n_init} args not supported (max 4)", node)
            return obj

        # Check if this is an actual closure variable vs a raw function pointer
        _, tag = self.variables.get(name, (None, "int"))
        is_closure = (tag == "closure")

        # Handle f(*args) — Starred arg in closure/function-pointer call.
        # Common in decorator wrappers: def wrapper(*args): return f(*args)
        # Uses closure_call_list which unpacks the args list at runtime
        # and dispatches to the function pointer with the right arity.
        has_starred = any(isinstance(a, ast.Starred) for a in node.args)
        if has_starred and n_args == 1 and isinstance(node.args[0], ast.Starred):
            args_list = self._emit_expr_value(node.args[0].value)
            if isinstance(args_list.type, ir.IntType):
                args_list = self.builder.inttoptr(args_list, i8_ptr)
            ptr = self.builder.inttoptr(val, i8_ptr) if isinstance(val.type, ir.IntType) else val
            return self.builder.call(
                self.runtime["closure_call_list"], [ptr, args_list])

        if is_closure:
            ptr = self.builder.inttoptr(val, i8_ptr) if isinstance(val.type, ir.IntType) else val
            if n_args == 0:
                return self.builder.call(self.runtime["closure_call0"], [ptr])
            elif n_args == 1:
                a = self._emit_expr_value(node.args[0])
                return self.builder.call(self.runtime["closure_call1"], [ptr, a])
            elif n_args == 2:
                a = self._emit_expr_value(node.args[0])
                b = self._emit_expr_value(node.args[1])
                return self.builder.call(self.runtime["closure_call2"], [ptr, a, b])
        else:
            # Raw function pointer (from lambda or passed as argument)
            ptr = self.builder.inttoptr(val, i8_ptr) if isinstance(val.type, ir.IntType) else val
            if n_args == 0:
                return self.builder.call(self.runtime["call_ptr0"], [ptr])
            elif n_args == 1:
                a = self._emit_expr_value(node.args[0])
                return self.builder.call(self.runtime["call_ptr1"], [ptr, a])
            elif n_args == 2:
                a = self._emit_expr_value(node.args[0])
                b = self._emit_expr_value(node.args[1])
                return self.builder.call(self.runtime["call_ptr2"], [ptr, a, b])

        raise CodeGenError(f"Function call with {n_args} args not supported for variable '{name}'", node)

    def _emit_constructor(self, node: ast.Call) -> ir.Value:
        """Emit a class constructor call: ClassName(args)."""
        class_name = node.func.id
        # Resolve to monomorphized variant if the class has scalar-conflicting
        # constructor sigs. This returns the variant's mangled name (e.g.
        # Processor__i for int instances, Processor__d for float).
        if class_name in self._monomorphized_classes:
            class_name = self._resolve_class_specialization(
                class_name, node.args, node.keywords)
        cls_info = self._user_classes[class_name]

        # Create new object
        class_id = self.builder.load(cls_info.class_id_global)
        obj = self.builder.call(self.runtime["obj_new"], [class_id])

        def coerce_to_i64(v):
            if isinstance(v.type, ir.PointerType):
                return self.builder.ptrtoint(v, i64)
            elif isinstance(v.type, ir.DoubleType):
                return self.builder.bitcast(v, i64)
            elif isinstance(v.type, ir.IntType) and v.type.width != 64:
                return self.builder.zext(v, i64)
            return v

        # Call __init__ via runtime dispatch — coerce all args to i64
        init_args = []
        for arg_node in node.args:
            v = self._emit_expr_value(arg_node)
            init_args.append(coerce_to_i64(v))

        defaults = cls_info.init_defaults or []

        # Handle keyword arguments
        if node.keywords:
            # Get __init__ param names
            init_ast = cls_info.method_asts.get("__init__") if cls_info.method_asts else None
            if init_ast is not None:
                init_params = [a.arg for a in init_ast.args.args[1:]]  # skip self
                kw_values: dict[int, ir.Value] = {}
                for kw in node.keywords:
                    if kw.arg is None:
                        continue
                    if kw.arg not in init_params:
                        raise CodeGenError(
                            f"{class_name}() got unexpected keyword argument '{kw.arg}'",
                            node,
                        )
                    idx = init_params.index(kw.arg)
                    if idx < len(init_args):
                        raise CodeGenError(
                            f"{class_name}() got multiple values for argument '{kw.arg}'",
                            node,
                        )
                    kw_values[idx] = coerce_to_i64(self._emit_expr_value(kw.value))
                while len(init_args) < cls_info.init_arg_count:
                    idx = len(init_args)
                    if idx in kw_values:
                        init_args.append(kw_values[idx])
                    else:
                        default_idx = idx - (cls_info.init_arg_count - len(defaults))
                        if default_idx >= 0 and default_idx < len(defaults):
                            v = self._emit_expr_value(defaults[default_idx])
                            init_args.append(coerce_to_i64(v))
                        else:
                            raise CodeGenError(
                                f"{class_name}() missing argument at position {idx}",
                                node,
                            )

        # Fill in defaults for missing args (positional-only case)
        n_provided = len(init_args)
        if n_provided < cls_info.init_arg_count:
            n_defaults_to_use = cls_info.init_arg_count - n_provided
            defaults_start = len(defaults) - n_defaults_to_use
            if defaults_start < 0:
                raise CodeGenError(
                    f"{class_name}() missing required argument(s)", node,
                )
            for default_node in defaults[defaults_start:]:
                v = self._emit_expr_value(default_node)
                init_args.append(coerce_to_i64(v))

        # Direct __init__ dispatch: since the class is known statically, we
        # can call the init function directly instead of going through
        # fastpy_obj_call_initN's method name lookup. (The runtime fallback
        # is still used for classes without a user-defined __init__.)
        init_fn = cls_info.methods.get("__init__") if cls_info.methods else None
        init_info = (self._user_functions.get(f"{class_name}.__init__")
                     if init_fn is not None else None)
        n_args = len(init_args)
        if init_fn is not None:
            direct_args = [obj]  # first param is self (i8*)
            if init_info is not None and init_info.uses_fv_abi:
                # FV-ABI init: wrap each arg as FpyValue, preserving
                # runtime tags (None, obj, etc.) through the boundary.
                for idx, arg_node in enumerate(node.args[:n_args]):
                    fv = self._load_or_wrap_fv(arg_node)
                    direct_args.append(fv)
                # Fill defaults if needed
                for d_idx in range(len(node.args), n_args):
                    val = init_args[d_idx]
                    # Determine the AST node for proper wrapping
                    default_offset = d_idx - (cls_info.init_arg_count - len(defaults))
                    d_node = (defaults[default_offset]
                              if 0 <= default_offset < len(defaults)
                              else None)
                    fv = self._wrap_arg_value(val, d_node)
                    direct_args.append(fv)
            else:
                # Legacy (non-FV-ABI) init: coerce args to declared types.
                for val, param in zip(init_args, list(init_fn.args)[1:]):
                    if val.type != param.type:
                        if isinstance(param.type, ir.IntType) and isinstance(val.type, ir.PointerType):
                            val = self.builder.ptrtoint(val, param.type)
                        elif isinstance(param.type, ir.PointerType) and isinstance(val.type, ir.IntType):
                            val = self.builder.inttoptr(val, param.type)
                        elif isinstance(param.type, ir.DoubleType) and isinstance(val.type, ir.IntType):
                            val = self.builder.bitcast(val, param.type)
                        elif isinstance(param.type, ir.IntType) and isinstance(val.type, ir.DoubleType):
                            val = self.builder.bitcast(val, param.type)
                    direct_args.append(val)
            self.builder.call(init_fn, direct_args)
        elif n_args == 0:
            self.builder.call(self.runtime["obj_call_init0"], [obj])
        elif n_args == 1:
            self.builder.call(self.runtime["obj_call_init1"], [obj, init_args[0]])
        elif n_args == 2:
            self.builder.call(self.runtime["obj_call_init2"], [obj, init_args[0], init_args[1]])
        elif n_args == 3:
            self.builder.call(self.runtime["obj_call_init3"],
                              [obj, init_args[0], init_args[1], init_args[2]])
        elif n_args == 4:
            self.builder.call(self.runtime["obj_call_init4"],
                              [obj, init_args[0], init_args[1], init_args[2], init_args[3]])
        else:
            raise CodeGenError(f"Constructor with {n_args} args not yet supported (max 4)", node)

        return obj

    def _emit_user_call(self, node: ast.Call) -> ir.Value | None:
        """Emit a call to a user-defined function. Returns the LLVM value (or None for void)."""
        # Expand **dict_literal to individual keywords at compile time.
        # E.g., f(**{"a": 1, "b": 2}) → f(a=1, b=2)
        if node.keywords:
            expanded = []
            for kw in node.keywords:
                if kw.arg is None and isinstance(kw.value, ast.Dict):
                    # **{key: val, ...} — expand to individual keywords
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            expanded.append(ast.keyword(arg=k.value, value=v))
                else:
                    expanded.append(kw)
            if expanded != node.keywords:
                node = ast.Call(func=node.func, args=node.args,
                                keywords=expanded)
        name = node.func.id
        # Resolve monomorphized specializations: if the function was split into
        # multiple specializations at declaration time, pick the one that
        # matches this call site's argument types.
        if name in self._monomorphized:
            name = self._resolve_specialization(
                name, node.args, node.keywords)
        info = self._user_functions[name]

        # Check if this is a *args or **kwargs function
        if (info.is_vararg or info.is_kwarg) and info.param_count == 1:
            # Pack all provided args into a list
            list_ptr = self.builder.call(self.runtime["list_new"], [])
            for arg_node in node.args:
                self._emit_list_append_expr(list_ptr, arg_node)
            # For **kwargs, pack keyword args into a dict
            if node.keywords:
                dict_ptr = self.builder.call(self.runtime["dict_new"], [])
                for kw in node.keywords:
                    key = self._make_string_constant(kw.arg)
                    val = self._emit_expr_value(kw.value)
                    tag, data = self._bare_to_tag_data(val, kw.value)
                    self.builder.call(self.runtime["dict_set_fv"],
                                      [dict_ptr, key, ir.Constant(i32, tag), data])
                result = self.builder.call(info.func, [dict_ptr])
            else:
                result = self.builder.call(info.func, [list_ptr])
            return result if info.ret_tag != "void" else None

        # Evaluate provided arguments (handling *args starred unpack)
        args = []
        for arg_node in node.args:
            if isinstance(arg_node, ast.Starred):
                # *args_list — expand into individual elements based on target arity.
                list_val = self._emit_expr_value(arg_node.value)
                remaining = info.param_count - len(args)
                elem_type = self._get_list_elem_type(arg_node.value)
                for i in range(remaining):
                    elem = self._list_get_as_bare(list_val, ir.Constant(i64, i), elem_type)
                    args.append(elem)
                break  # starred must be last
            val = self._emit_expr_value(arg_node)
            args.append(val)

        # Handle keyword arguments by mapping them to positional slots
        if node.keywords:
            fn_def = getattr(self, '_function_def_nodes', {}).get(name)
            if fn_def is not None:
                param_names = [a.arg for a in fn_def.args.args]
                param_names += [a.arg for a in fn_def.args.kwonlyargs]
                # For each keyword, find the param position and fill
                kw_values: dict[int, ir.Value] = {}
                for kw in node.keywords:
                    if kw.arg is None:
                        continue  # **kwargs spread, handled elsewhere
                    if kw.arg not in param_names:
                        raise CodeGenError(
                            f"{name}() got unexpected keyword argument '{kw.arg}'",
                            node,
                        )
                    idx = param_names.index(kw.arg)
                    if idx < len(args):
                        raise CodeGenError(
                            f"{name}() got multiple values for argument '{kw.arg}'",
                            node,
                        )
                    kw_values[idx] = self._emit_expr_value(kw.value)
                # Fill gaps from positional to first keyword slot with defaults,
                # then keyword values, then defaults for remaining.
                while len(args) < info.param_count:
                    idx = len(args)
                    if idx in kw_values:
                        args.append(kw_values[idx])
                    else:
                        # Use default for this position
                        default_idx = idx - (info.param_count - len(info.defaults))
                        if default_idx >= 0 and default_idx < len(info.defaults):
                            val = self._emit_expr_value(info.defaults[default_idx])
                            args.append(val)
                        else:
                            raise CodeGenError(
                                f"{name}() missing required argument at position {idx}",
                                node,
                            )

        # Fill in defaults for missing arguments
        n_provided = len(args)
        if n_provided < info.min_args:
            raise CodeGenError(
                f"{name}() missing {info.min_args - n_provided} required argument(s)",
                node,
            )
        if n_provided > info.param_count:
            raise CodeGenError(
                f"{name}() takes {info.param_count} arguments but {n_provided} were given",
                node,
            )

        # Append default values for unprovided parameters.
        # Track their AST nodes so the FV coercion loop can use
        # _load_or_wrap_fv (preserves None tag for `default=None`).
        default_ast_nodes: list[ast.expr] = []
        if n_provided < info.param_count:
            # defaults are right-aligned: defaults[0] is for param[param_count - len(defaults)]
            n_defaults_to_use = info.param_count - n_provided
            defaults_start = len(info.defaults) - n_defaults_to_use
            for default_node in info.defaults[defaults_start:]:
                val = self._emit_expr_value(default_node)
                args.append(val)
                default_ast_nodes.append(default_node)

        # Coerce arguments to function signature
        coerced = []
        if info.uses_fv_abi:
            # Post-refactor: each param is FpyValue. Wrap each bare arg.
            # Match args to AST nodes for AST-based tag inference; when there
            # are more args than AST nodes (starred unpack / defaults), use
            # the tracked default AST node.
            for i, val in enumerate(args):
                if i < len(node.args) and not isinstance(node.args[i], ast.Starred):
                    arg_node = node.args[i]
                elif i >= n_provided and (i - n_provided) < len(default_ast_nodes):
                    arg_node = default_ast_nodes[i - n_provided]
                else:
                    arg_node = None
                # For arguments that are FV-backed (Names with fpy_val
                # allocas, or Attributes on obj receivers), use
                # _load_or_wrap_fv to preserve the runtime tag. This
                # avoids the unwrap→re-wrap round-trip that loses NONE
                # tags (e.g. `func(obj.attr)` where attr is None, or
                # `func(var)` where var holds None via an attr load).
                if arg_node is not None:
                    fv = self._load_or_wrap_fv(arg_node)
                    coerced.append(fv)
                    continue
                fv = self._wrap_arg_value(val, arg_node)
                coerced.append(fv)
        else:
            for val, param in zip(args, info.func.args):
                if val.type != param.type:
                    if isinstance(param.type, ir.IntType) and isinstance(val.type, ir.DoubleType):
                        val = self.builder.fptosi(val, param.type)
                    elif isinstance(param.type, ir.DoubleType) and isinstance(val.type, ir.IntType):
                        val = self.builder.sitofp(val, param.type)
                    elif isinstance(param.type, ir.IntType) and isinstance(val.type, ir.PointerType):
                        val = self.builder.ptrtoint(val, param.type)
                    elif isinstance(param.type, ir.PointerType) and isinstance(val.type, ir.IntType):
                        val = self.builder.inttoptr(val, param.type)
                coerced.append(val)

        result = self.builder.call(info.func, coerced)

        # Unwrap FV return to the caller's expected bare type
        if info.uses_fv_abi and info.ret_tag != "void":
            result = self._unwrap_return_value(result, info)

        return result if info.ret_tag != "void" else None

    def _emit_user_call_fv(self, node: ast.Call) -> ir.Value:
        """Emit a user function call and return the raw FpyValue without
        unwrapping.  Used by _load_or_wrap_fv so the runtime tag from the
        callee is preserved (instead of being discarded by _unwrap_return_value
        and re-inferred from the static type)."""
        # Expand **dict_literal to individual keywords
        if node.keywords:
            expanded = []
            for kw in node.keywords:
                if kw.arg is None and isinstance(kw.value, ast.Dict):
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            expanded.append(ast.keyword(arg=k.value, value=v))
                else:
                    expanded.append(kw)
            if expanded != node.keywords:
                node = ast.Call(func=node.func, args=node.args,
                                keywords=expanded)
        name = node.func.id
        if name in self._monomorphized:
            name = self._resolve_specialization(
                name, node.args, node.keywords)
        info = self._user_functions[name]

        # Same argument handling as _emit_user_call, just skip the unwrap.
        # Handle *args/**kwargs functions
        if (info.is_vararg or info.is_kwarg) and info.param_count == 1:
            list_ptr = self.builder.call(self.runtime["list_new"], [])
            for arg_node in node.args:
                self._emit_list_append_expr(list_ptr, arg_node)
            if node.keywords:
                dict_ptr = self.builder.call(self.runtime["dict_new"], [])
                for kw in node.keywords:
                    key = self._make_string_constant(kw.arg)
                    val = self._emit_expr_value(kw.value)
                    tag, data = self._bare_to_tag_data(val, kw.value)
                    self.builder.call(self.runtime["dict_set_fv"],
                                      [dict_ptr, key, ir.Constant(i32, tag), data])
                return self.builder.call(info.func, [dict_ptr])
            return self.builder.call(info.func, [list_ptr])

        # Regular call: evaluate args, apply defaults, coerce
        args = []
        arg_source_nodes: list = []  # Track AST nodes for wrapping
        for arg_node in node.args:
            if isinstance(arg_node, ast.Starred):
                list_val = self._emit_expr_value(arg_node.value)
                remaining = info.param_count - len(args)
                elem_type = self._get_list_elem_type(arg_node.value)
                for i in range(remaining):
                    elem = self._list_get_as_bare(list_val, ir.Constant(i64, i), elem_type)
                    args.append(elem)
                    arg_source_nodes.append(None)
                break
            val = self._emit_expr_value(arg_node)
            args.append(val)
            arg_source_nodes.append(arg_node)

        # Handle keyword arguments by mapping them to positional slots
        if node.keywords:
            fn_def = getattr(self, '_function_def_nodes', {}).get(name)
            if fn_def is not None:
                param_names = [a.arg for a in fn_def.args.args]
                param_names += [a.arg for a in fn_def.args.kwonlyargs]
                kw_values: dict[int, tuple] = {}
                for kw in node.keywords:
                    if kw.arg is None:
                        continue
                    if kw.arg not in param_names:
                        raise CodeGenError(
                            f"{name}() got unexpected keyword argument '{kw.arg}'",
                            node,
                        )
                    idx = param_names.index(kw.arg)
                    if idx < len(args):
                        raise CodeGenError(
                            f"{name}() got multiple values for argument '{kw.arg}'",
                            node,
                        )
                    kw_values[idx] = (self._emit_expr_value(kw.value), kw.value)
                while len(args) < info.param_count:
                    idx = len(args)
                    if idx in kw_values:
                        args.append(kw_values[idx][0])
                        arg_source_nodes.append(kw_values[idx][1])
                    else:
                        default_idx = idx - (info.param_count - len(info.defaults))
                        if default_idx >= 0 and default_idx < len(info.defaults):
                            val = self._emit_expr_value(info.defaults[default_idx])
                            args.append(val)
                            arg_source_nodes.append(info.defaults[default_idx])
                        else:
                            raise CodeGenError(
                                f"{name}() missing required argument at position {idx}",
                                node,
                            )

        n_provided = len(args)
        if n_provided < info.param_count:
            n_defaults_to_use = info.param_count - n_provided
            defaults_start = len(info.defaults) - n_defaults_to_use
            for default_node in info.defaults[defaults_start:]:
                val = self._emit_expr_value(default_node)
                args.append(val)
                arg_source_nodes.append(default_node)

        coerced = []
        for i, val in enumerate(args):
            arg_node = arg_source_nodes[i] if i < len(arg_source_nodes) else None
            # Use _load_or_wrap_fv for all AST-backed args to preserve
            # runtime tags (None, obj, etc.) through the FV-ABI boundary.
            if arg_node is not None:
                fv = self._load_or_wrap_fv(arg_node)
                coerced.append(fv)
                continue
            fv = self._wrap_arg_value(val, arg_node)
            coerced.append(fv)

        # Call the function — return the raw FpyValue, no unwrap
        return self.builder.call(info.func, coerced)

    def _wrap_arg_value(self, val: ir.Value, arg_node: ast.expr | None) -> ir.Value:
        """Wrap a bare argument value into an FpyValue for the FV-ABI call.

        `arg_node` is optional — when None (starred unpack, defaults), we fall
        back to LLVM-type-based tag assignment.
        """
        # None constants and None-tagged variables must use NONE tag, not INT.
        # Without this, `func(None)` passes {tag=INT, data=0} and `x is None`
        # inside the function returns False.
        if (arg_node is not None
                and isinstance(arg_node, ast.Constant)
                and arg_node.value is None):
            return self._fv_none()
        if (arg_node is not None
                and isinstance(arg_node, ast.Name)
                and arg_node.id in self.variables
                and self.variables[arg_node.id][1] == "none"):
            return self._fv_none()
        if isinstance(val.type, ir.IntType):
            if val.type.width == 32:
                return self._fv_from_bool(val)
            # Bool constants (True/False) are emitted as i64 but should be
            # tagged BOOL. Check the AST node.
            if (arg_node is not None
                    and isinstance(arg_node, ast.Constant)
                    and isinstance(arg_node.value, bool)):
                return self._fv_from_bool(self.builder.trunc(val, i32))
            # Bool-typed variables should also keep their BOOL tag
            if (arg_node is not None
                    and isinstance(arg_node, ast.Name)
                    and arg_node.id in self.variables
                    and self.variables[arg_node.id][1] == "bool"):
                return self._fv_from_bool(self.builder.trunc(val, i32))
            return self._fv_from_int(val)
        if isinstance(val.type, ir.DoubleType):
            return self._fv_from_float(val)
        if isinstance(val.type, ir.PointerType):
            if arg_node is not None:
                if self._is_list_expr(arg_node) or self._is_tuple_expr(arg_node):
                    return self._fv_from_list(val)
                if self._is_dict_expr(arg_node):
                    return self._fv_from_list(val)
                if self._is_obj_expr(arg_node):
                    return self._fv_from_obj(val)
            return self._fv_from_str(val)
        raise CodeGenError(f"Cannot wrap argument of type {val.type}")

    def _unwrap_return_value(self, fv: ir.Value, info: "FuncInfo") -> ir.Value:
        """Unwrap an FpyValue return into the caller's expected bare type.

        The expected type is `info.static_ret_type`.
        """
        ret_type = info.static_ret_type
        if isinstance(ret_type, ir.IntType) and ret_type.width == 64:
            return self._fv_as_int(fv)
        if isinstance(ret_type, ir.IntType) and ret_type.width == 32:
            # Bool — extract data as i64 then truncate
            return self.builder.trunc(self._fv_as_int(fv), i32)
        if isinstance(ret_type, ir.DoubleType):
            return self._fv_as_float(fv)
        if isinstance(ret_type, ir.PointerType):
            return self._fv_as_ptr(fv)
        # Fallback: treat as i64
        return self._fv_data_i64(fv)

    def _emit_print(self, node: ast.Call) -> None:
        """Emit a print() call."""
        # Extract sep= and end= keyword arguments (must be literal strings)
        sep = " "
        end = "\n"
        for kw in node.keywords:
            if kw.arg == "sep":
                if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                    raise CodeGenError("print(sep=) must be a literal string", node)
                sep = kw.value.value
            elif kw.arg == "end":
                if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                    raise CodeGenError("print(end=) must be a literal string", node)
                end = kw.value.value
            else:
                raise CodeGenError(f"print() does not support keyword: {kw.arg}", node)

        if len(node.args) == 0:
            if end:
                if end == "\n":
                    self.builder.call(self.runtime["print_newline"], [])
                else:
                    end_ptr = self._make_string_constant(end)
                    self.builder.call(self.runtime["write_str"], [end_ptr])
            return

        # Handle starred args: print(*[1,2,3]) → iterate the list
        has_star = any(isinstance(a, ast.Starred) for a in node.args)
        if has_star:
            sep_ptr = self._make_string_constant(sep)
            first_alloca = self._create_entry_alloca(ir.IntType(1), "print.first")
            self.builder.store(ir.Constant(ir.IntType(1), 1), first_alloca)
            for arg in node.args:
                if isinstance(arg, ast.Starred):
                    # Iterate the list and print each element
                    lst = self._emit_expr_value(arg.value)
                    length = self.builder.call(
                        self.runtime["list_length"], [lst])
                    idx_alloca = self._create_entry_alloca(i64, "pstar.idx")
                    self.builder.store(ir.Constant(i64, 0), idx_alloca)
                    cond_b = self._new_block("pstar.cond")
                    body_b = self._new_block("pstar.body")
                    end_b = self._new_block("pstar.end")
                    self.builder.branch(cond_b)
                    self.builder.position_at_end(cond_b)
                    idx = self.builder.load(idx_alloca)
                    self.builder.cbranch(
                        self.builder.icmp_signed("<", idx, length),
                        body_b, end_b)
                    self.builder.position_at_end(body_b)
                    idx = self.builder.load(idx_alloca)
                    is_first = self.builder.load(first_alloca)
                    not_first = self.builder.not_(is_first)
                    sep_b = self._new_block("pstar.sep")
                    nosep_b = self._new_block("pstar.nosep")
                    self.builder.cbranch(not_first, sep_b, nosep_b)
                    self.builder.position_at_end(sep_b)
                    self.builder.call(self.runtime["write_str"], [sep_ptr])
                    self.builder.branch(nosep_b)
                    self.builder.position_at_end(nosep_b)
                    self.builder.store(
                        ir.Constant(ir.IntType(1), 0), first_alloca)
                    # Print element via FV
                    tag_s = self._create_entry_alloca(i32, "pstar.tag")
                    data_s = self._create_entry_alloca(i64, "pstar.data")
                    self.builder.call(self.runtime["list_get_fv"],
                                      [lst, idx, tag_s, data_s])
                    tag = self.builder.load(tag_s)
                    data = self.builder.load(data_s)
                    self.builder.call(
                        self.runtime["fv_write"], [tag, data])
                    self.builder.store(
                        self.builder.add(idx, ir.Constant(i64, 1)),
                        idx_alloca)
                    self.builder.branch(cond_b)
                    self.builder.position_at_end(end_b)
                else:
                    # Normal arg
                    is_first = self.builder.load(first_alloca)
                    not_first = self.builder.not_(is_first)
                    sep_b2 = self._new_block("print.sep")
                    nosep_b2 = self._new_block("print.nosep")
                    self.builder.cbranch(not_first, sep_b2, nosep_b2)
                    self.builder.position_at_end(sep_b2)
                    self.builder.call(self.runtime["write_str"], [sep_ptr])
                    self.builder.branch(nosep_b2)
                    self.builder.position_at_end(nosep_b2)
                    self.builder.store(
                        ir.Constant(ir.IntType(1), 0), first_alloca)
                    self._emit_write_single(arg)
            if end == "\n":
                self.builder.call(self.runtime["print_newline"], [])
            elif end:
                end_ptr = self._make_string_constant(end)
                self.builder.call(self.runtime["write_str"], [end_ptr])
            return

        # Simple case: no custom sep/end, single arg — use fast path
        if len(node.args) == 1 and sep == " " and end == "\n":
            self._emit_print_single(node.args[0])
            return

        # Write each arg separated by `sep`, then write `end`
        for i, arg in enumerate(node.args):
            if i > 0:
                if sep == " ":
                    self.builder.call(self.runtime["write_space"], [])
                else:
                    sep_ptr = self._make_string_constant(sep)
                    self.builder.call(self.runtime["write_str"], [sep_ptr])
            self._emit_write_single(arg)
        if end == "\n":
            self.builder.call(self.runtime["print_newline"], [])
        elif end:
            end_ptr = self._make_string_constant(end)
            self.builder.call(self.runtime["write_str"], [end_ptr])

    def _emit_print_single(self, node: ast.expr) -> None:
        """Emit print() for a single argument via FpyValue runtime dispatch.

        Evaluates the expression, wraps it into an FpyValue (tag, data),
        and calls fv_print which dispatches by tag at runtime. This replaces
        the old compile-time type dispatch (~50 lines of AST-level checks).
        """
        fv = self._load_or_wrap_fv(node)
        tag, data = self._fv_unpack(fv)
        self.builder.call(self.runtime["fv_print"], [tag, data])

    def _load_or_wrap_fv(self, node: ast.expr) -> ir.Value:
        """Get an FpyValue for `node`, preferring the raw stored FV when the
        node is a Name backed by an %fpyvalue alloca, a dict/list subscript,
        or an object attribute access. This preserves the runtime tag
        (which can differ from the compile-time inferred type for
        mixed-type containers and polymorphic attributes).
        """
        # CPython pyobj-tagged variables: convert the PyObject* to a native
        # FpyValue via the bridge. Without this, the OBJ tag + raw PyObject*
        # data would crash fv_print (expects an FpyObj*, not PyObject*).
        if (isinstance(node, ast.Name)
                and node.id in self.variables
                and self.variables[node.id][1] == "pyobj"):
            ptr = self._load_variable(node.id, node)
            if isinstance(ptr.type, ir.IntType):
                ptr = self.builder.inttoptr(ptr, i8_ptr)
            tag_slot = self._create_entry_alloca(i32, "pyvar.tag")
            data_slot = self._create_entry_alloca(i64, "pyvar.data")
            self.builder.call(self.runtime["cpython_to_fv"],
                              [ptr, tag_slot, data_slot])
            return self._fv_build_from_slots(
                self.builder.load(tag_slot),
                self.builder.load(data_slot))
        if (self._USE_FV_LOCALS and isinstance(node, ast.Name)
                and node.id in self.variables
                and node.id not in self._global_vars):
            alloca, type_tag = self.variables[node.id]
            if (type_tag != "cell"
                    and isinstance(alloca.type, ir.PointerType)
                    and alloca.type.pointee is fpy_val):
                return self.builder.load(alloca, name=f"{node.id}.fv")
        # Dict subscript: load the FV directly to preserve the runtime tag
        # (avoids the dict-with-int / dict-with-list heuristic for printing).
        if (isinstance(node, ast.Subscript)
                and self._is_dict_expr(node.value)
                and not isinstance(node.slice, ast.Slice)):
            obj = self._emit_expr_value(node.value)
            key = self._emit_expr_value(node.slice)
            if isinstance(key.type, ir.PointerType):
                tag_slot = self._create_entry_alloca(i32, "dget.tag")
                data_slot = self._create_entry_alloca(i64, "dget.data")
                self.builder.call(self.runtime["dict_get_fv"],
                                  [obj, key, tag_slot, data_slot])
                return self._fv_build_from_slots(
                    self.builder.load(tag_slot),
                    self.builder.load(data_slot))
        # List / tuple subscript: load FV directly for runtime-tag print.
        # Tuples can have heterogeneous types (int, str, float, etc.),
        # so the only correct way to access an element is via the runtime
        # tag.
        if (isinstance(node, ast.Subscript)
                and (self._is_list_expr(node.value)
                     or self._is_tuple_expr(node.value))
                and not isinstance(node.slice, ast.Slice)):
            obj = self._emit_expr_value(node.value)
            index = self._emit_expr_value(node.slice)
            tag, data = self._fv_list_get(obj, index)
            return self._fv_build_from_slots(tag, data)
        # CPython module attribute (e.g. math.pi) — must come BEFORE the
        # generic Attribute handler which calls obj_get_fv.
        # Native module attribute (math.pi): return constant as FpyValue
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in self.variables
                and self.variables[node.value.id][1] == "native_mod"):
            val = self._emit_native_module_attr(node.value.id, node.attr)
            if val is not None:
                return self._wrap_for_print(val, node)
        # Native module call in print context (print(math.sqrt(x)))
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in self.variables
                and self.variables[node.func.value.id][1] == "native_mod"):
            val = self._emit_native_module_call(
                node.func.value.id, node.func.attr, node)
            if val is not None:
                return self._wrap_for_print(val, node)
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in self.variables
                and self.variables[node.value.id][1] == "pyobj"):
            obj = self._load_variable(node.value.id, node)
            if isinstance(obj.type, ir.IntType):
                obj = self.builder.inttoptr(obj, i8_ptr)
            attr_name = self._make_string_constant(node.attr)
            pyobj = self.builder.call(
                self.runtime["cpython_getattr"], [obj, attr_name])
            tag_slot = self._create_entry_alloca(i32, "pyattr.tag")
            data_slot = self._create_entry_alloca(i64, "pyattr.data")
            self.builder.call(self.runtime["cpython_to_fv"],
                              [pyobj, tag_slot, data_slot])
            return self._fv_build_from_slots(
                self.builder.load(tag_slot),
                self.builder.load(data_slot))
        # Nested class chained access: Outer.Inner.x
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id in self._user_classes
                and node.value.attr in self._user_classes):
            inner_class = node.value.attr
            const_attrs = self._class_const_attrs.get(inner_class, {})
            if node.attr in const_attrs:
                val = self._emit_expr_value(const_attrs[node.attr])
                return self._wrap_for_print(val, node)

        # type(X).__name__ pattern — resolved at compile time
        if (isinstance(node, ast.Attribute) and node.attr == "__name__"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "type"
                and len(node.value.args) == 1
                and isinstance(node.value.args[0], ast.Name)):
            value = self._emit_expr_value(node)
            return self._wrap_for_print(value, node)
        # @property dispatch in FV context: call the getter and wrap result
        if isinstance(node, ast.Attribute):
            prop_cls = self._infer_object_class(node.value)
            if prop_cls:
                prop_info = self._user_classes.get(prop_cls)
                if (prop_info and prop_info.properties
                        and node.attr in prop_info.properties):
                    obj = self._emit_expr_value(node.value)
                    if isinstance(obj.type, ir.IntType):
                        obj = self.builder.inttoptr(obj, i8_ptr)
                    method_func = prop_info.methods.get(node.attr)
                    if method_func:
                        result = self.builder.call(method_func, [obj])
                        return self._wrap_for_print(result, node)
        # Object attribute access: load the FV directly via obj_get_slot
        # (or obj_get_fv as fallback) so the runtime tag is preserved.
        if (isinstance(node, ast.Attribute)
                and not (isinstance(node.value, ast.Name)
                         and node.value.id in self._user_classes)):
            obj = self._emit_expr_value(node.value)
            if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
                obj = self.builder.inttoptr(obj, i8_ptr, name="obj.ptr")
            if isinstance(obj.type, ir.PointerType):
                slot_idx = self._get_attr_slot(node)
                if slot_idx is not None:
                    tag_val, data_val = self._emit_slot_get_direct(
                        obj, slot_idx)
                    return self._fv_build_from_slots(tag_val, data_val)
                tag_slot = self._create_entry_alloca(i32, "aget.tag")
                data_slot = self._create_entry_alloca(i64, "aget.data")
                attr_name = self._make_string_constant(node.attr)
                self.builder.call(self.runtime["obj_get_fv"],
                                  [obj, attr_name, tag_slot, data_slot])
                return self._fv_build_from_slots(
                    self.builder.load(tag_slot),
                    self.builder.load(data_slot))
        # User function call returning FpyValue: emit the call and return the
        # FV directly, preserving the runtime tag from the callee. Without
        # this, _emit_user_call unwraps based on the static return type,
        # losing the runtime tag for polymorphic returns.
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in self._user_functions):
            info = self._user_functions[node.func.id]
            if info.uses_fv_abi and info.ret_tag != "void":
                return self._emit_user_call_fv(node)
        # Closure call: read fpy_ret_tag to get the runtime tag
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in self.variables
                and self.variables[node.func.id][1] == "closure"):
            data = self._emit_expr_value(node)
            # Read the tag stored by the closure body's ret instruction
            tag = self.builder.call(self.runtime["get_ret_tag"], [])
            if isinstance(data.type, ir.PointerType):
                data = self.builder.ptrtoint(data, i64)
            elif isinstance(data.type, ir.IntType) and data.type.width != 64:
                data = self.builder.zext(data, i64)
            return self._fv_build_from_slots(tag, data)
        # CPython module method call (e.g. math.sqrt(x)) — returns FpyValue
        # with the runtime tag set by the bridge's type conversion.
        # Also handles chained attrs: os.path.exists(x) where os is pyobj.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            recv = node.func.value
            is_pyobj_recv = (
                (isinstance(recv, ast.Name)
                 and recv.id in self.variables
                 and self.variables[recv.id][1] == "pyobj")
                or (isinstance(recv, ast.Attribute)
                    and isinstance(recv.value, ast.Name)
                    and recv.value.id in self.variables
                    and self.variables[recv.value.id][1] == "pyobj"))
            if is_pyobj_recv:
                return self._emit_cpython_method_call(node)
        # Direct CPython callable (from `from module import func`)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in self.variables
                and self.variables[node.func.id][1] == "pyobj"):
            return self._emit_cpython_direct_call_expr(node)
        value = self._emit_expr_value(node)
        return self._wrap_for_print(value, node)

    def _wrap_for_print(self, value: ir.Value, node: ast.expr) -> ir.Value:
        """Wrap a bare LLVM value into an FpyValue for printing.

        Uses AST-level type checks for pointer disambiguation (str vs list
        vs dict vs tuple vs obj). Falls back to LLVM type for scalars.
        """
        # Constants: inline the tag
        if isinstance(node, ast.Constant):
            if node.value is None:
                return self._fv_none()
            if isinstance(node.value, bool):
                return self._fv_from_bool(value)

        # Named variables: use the variable's stored type_tag (survives load/unwrap)
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, var_tag = self.variables[node.id]
            if var_tag == "none":
                return self._fv_none()
            if var_tag == "bool":
                return self._fv_from_bool(value)
            if var_tag == "dict":
                return self._fv_from_dict(value)
            if var_tag == "obj":
                return self._fv_from_obj(value)
            if var_tag == "tuple" or var_tag.startswith("list"):
                return self._fv_from_list(value)
            if var_tag == "str":
                return self._fv_from_str(value)
            if var_tag == "float":
                return self._fv_from_float(value)
            if var_tag == "int":
                return self._fv_from_int(value)

        # Containers: tag from AST
        if isinstance(value.type, ir.PointerType):
            if self._is_list_expr(node):
                return self._fv_from_list(value)
            if self._is_tuple_expr(node):
                return self._fv_from_list(value)  # tuples are lists with is_tuple
            if self._is_dict_expr(node):
                return self._fv_from_dict(value)
            if self._is_obj_expr(node):
                return self._fv_from_obj(value)
            # Check function calls that return strings
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                if name in self._user_functions and self._user_functions[name].ret_tag == "str":
                    return self._fv_from_str(value)
            # Default pointer: string
            return self._fv_from_str(value)

        # BoolOp where all operands are boolean-typed: tag as BOOL.
        # (BoolOp uses an i64 alloca internally, so the LLVM type is i64,
        #  but in Python `True and False` is a bool, not an int.)
        if isinstance(node, ast.BoolOp) and all(
                self._is_bool_typed(v) for v in node.values):
            if isinstance(value.type, ir.IntType) and value.type.width == 64:
                value = self.builder.trunc(value, i32)
            return self._fv_from_bool(value)

        # Object method calls returning bool (i32 from _declare_class) —
        # the dispatch wrapper returns i64, so we need AST-level detection.
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(value.type, ir.IntType)
                and value.type.width == 64):
            ret = self._find_method_return_type(node.func.value, node.func.attr)
            if ret is not None and isinstance(ret, ir.IntType) and ret.width == 32:
                value = self.builder.trunc(value, i32)
                return self._fv_from_bool(value)

        # Compare and bool-typed expressions returning i64
        if (isinstance(value.type, ir.IntType) and value.type.width == 64
                and isinstance(node, ast.Compare)):
            return self._fv_from_bool(value)
        if (isinstance(value.type, ir.IntType) and value.type.width == 64
                and self._is_bool_typed(node)):
            return self._fv_from_bool(value)

        # Scalars: tag from LLVM type
        if isinstance(value.type, ir.IntType):
            if value.type.width == 32:
                return self._fv_from_bool(value)
            return self._fv_from_int(value)
        if isinstance(value.type, ir.DoubleType):
            return self._fv_from_float(value)
        # Fallback
        return self._fv_from_int(value)

    def _get_list_elem_type(self, node: ast.expr) -> str:
        """Get the element type of a list expression."""
        # Check from variable type tag
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, type_tag = self.variables[node.id]
            if ":" in type_tag:
                return type_tag.split(":")[1]
            # For tuples, check the literal definition for element type
            if type_tag == "tuple" and node.id in self._tuple_elem_types:
                return self._tuple_elem_types[node.id]
        # .values(), .items(), .keys() return lists of tagged values / strings.
        # For int-keyed dicts, keys() returns ints, not strings.
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("values", "items", "keys")):
            if (node.func.attr == "keys"
                    and isinstance(node.func.value, ast.Name)
                    and self._is_int_keyed_dict(node.func.value)):
                return "int"
            return "str"
        # sorted(dict) or sorted(dict.keys()) returns list of keys
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "sorted" and len(node.args) == 1):
            arg = node.args[0]
            if self._is_dict_expr(arg):
                if isinstance(arg, ast.Name) and self._is_int_keyed_dict(arg):
                    return "int"
                return "str"
            # sorted(dict.keys()) / sorted(dict.values())
            if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                    and arg.func.attr in ("keys", "values", "items")):
                if (arg.func.attr == "keys"
                        and isinstance(arg.func.value, ast.Name)
                        and self._is_int_keyed_dict(arg.func.value)):
                    return "int"
                return "str"
        # Check if this is a function call that returns a list of lists
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in self._user_functions:
                info = self._user_functions[node.func.id]
                if info.ret_tag == "ptr:list":
                    return "list"
        # Infer from AST
        return self._infer_list_elem_type(node)

    def _known_pointer_type(self, node: ast.expr) -> str | None:
        """If node is known to be a specific pointer kind at compile time,
        return 'list' / 'str' / 'dict' / 'tuple' / 'obj'. Return None if
        polymorphic or not a pointer. Used to detect type mismatches in
        binary operators (e.g., list + str should raise TypeError).
        """
        if isinstance(node, (ast.List, ast.ListComp, ast.Set,
                              ast.GeneratorExp)):
            return "list"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return "dict"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return "str"
        if isinstance(node, ast.JoinedStr):
            return "str"
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, tag = self.variables[node.id]
            if tag == "str":
                return "str"
            if tag.startswith("list"):
                return "list"
            if tag == "dict" or tag.startswith("dict:"):
                return "dict"
            if tag == "tuple":
                return "tuple"
            if tag == "obj":
                return "obj"
        return None

    def _emit_type_error(self, msg: str, node: ast.AST) -> ir.Value:
        """Emit a runtime TypeError raise with the given message and return
        a placeholder value. The raise aborts execution before the value is
        used, but we still need to return *something* of a matching LLVM
        type so the builder stays consistent."""
        name_ptr = self._make_string_constant("TypeError")
        exc_id = self.builder.call(self.runtime["exc_name_to_id"], [name_ptr])
        msg_ptr = self._make_string_constant(msg)
        self.builder.call(self.runtime["raise"], [exc_id, msg_ptr])
        # Early-return if not in try: mirrors _emit_raise behavior so the
        # error surfaces immediately rather than after more bad ops.
        if not self._in_try_block:
            ret_type = self.function.return_value.type
            if isinstance(ret_type, ir.VoidType):
                self.builder.ret_void()
            elif isinstance(ret_type, ir.LiteralStructType):
                self.builder.ret(self._fv_none())
            elif isinstance(ret_type, ir.DoubleType):
                self.builder.ret(ir.Constant(double, 0.0))
            elif isinstance(ret_type, ir.PointerType):
                self.builder.ret(ir.Constant(ret_type, None))
            else:
                self.builder.ret(ir.Constant(ret_type, 0))
            # Builder is now terminated; caller won't use the return value.
            # Create an unreachable block so subsequent IR emission has a
            # valid insertion point.
            unreachable = self.function.append_basic_block("after_raise")
            self.builder.position_at_end(unreachable)
        # Return a null pointer as placeholder (won't be reached).
        return ir.Constant(i8_ptr, None)

    def _is_set_expr(self, node: ast.expr) -> bool:
        """Check if an AST expression evaluates to a set (dict-backed)."""
        if isinstance(node, (ast.Set, ast.SetComp)):
            return True
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, type_tag = self.variables[node.id]
            return type_tag == "set"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "set":
                return True
        # Set operations produce sets
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, (ast.BitOr, ast.BitAnd, ast.BitXor)):
                if self._is_set_expr(node.left) or self._is_set_expr(node.right):
                    return True
            if isinstance(node.op, ast.Sub):
                if self._is_set_expr(node.left):
                    return True
        return False

    def _is_list_expr(self, node: ast.expr) -> bool:
        """Check if an AST expression evaluates to a list."""
        if isinstance(node, (ast.List, ast.ListComp, ast.GeneratorExp)):
            return True
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, type_tag = self.variables[node.id]
            return type_tag.startswith("list")
        # sorted(), reversed(), list() return lists (set() now returns dict-backed set)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("sorted", "reversed", "list", "enumerate", "zip", "map", "filter", "range"):
                return True
            # User functions that return lists (ret_tag "ptr" with list_vars)
            if node.func.id in self._user_functions:
                info = self._user_functions[node.func.id]
                if info.ret_tag in ("ptr", "ptr:list"):
                    return True
        # .split(), .keys(), .values(), .items(), .copy() return lists
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("split", "keys", "values", "items", "splitlines", "copy")):
            return True
        # User class method returning list
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if self._method_returns_list(node.func.value, node.func.attr):
                return True
        # List slicing returns a list
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            if self._is_list_expr(node.value):
                return True
        # Indexing a list-of-lists returns a list
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            if self._is_list_expr(node.value):
                elem_type = self._get_list_elem_type(node.value)
                if elem_type == "list":
                    return True
            # Indexing a dict-with-list-values returns a list
            if (isinstance(node.value, ast.Name)
                    and node.value.id in self._dict_var_list_values):
                return True
        # BinOp on lists (concatenation, set ops) returns a list
        if isinstance(node, ast.BinOp):
            if self._is_list_expr(node.left) or self._is_list_expr(node.right):
                return True
        # Object attribute access: obj.attr where attr is a list
        if isinstance(node, ast.Attribute):
            obj_cls = self._infer_object_class(node.value)
            if obj_cls and obj_cls in self._class_container_attrs:
                list_attrs, _ = self._class_container_attrs[obj_cls]
                if node.attr in list_attrs:
                    return True
        return False

    def _infer_object_class(self, node: ast.expr) -> str | None:
        """Try to determine the class of an object expression."""
        # Class constructor call: ClassName(...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in self._user_classes:
                # Resolve to variant for monomorphized classes so downstream
                # lookups (_per_class_float_attrs etc.) use the right variant.
                if node.func.id in self._monomorphized_classes:
                    return self._resolve_class_specialization(
                        node.func.id, node.args, node.keywords)
                return node.func.id
            # User function that returns an obj — infer the class from the
            # function's body (look for `return ClassName(...)` or `return
            # var_assigned_from_ClassName`).
            if node.func.id in self._user_functions:
                info = self._user_functions[node.func.id]
                if info.ret_tag == "obj":
                    fn_def = getattr(self, "_function_def_nodes", {}).get(
                        node.func.id)
                    if fn_def is not None:
                        # Find obj-typed vars in the function body
                        body_obj_classes: dict[str, str] = {}
                        for n in ast.walk(fn_def):
                            if (isinstance(n, ast.Assign)
                                    and len(n.targets) == 1
                                    and isinstance(n.targets[0], ast.Name)
                                    and isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Name)
                                    and n.value.func.id in self._user_classes):
                                body_obj_classes[n.targets[0].id] = n.value.func.id
                        # Check return statements
                        for n in ast.walk(fn_def):
                            if isinstance(n, ast.Return) and n.value is not None:
                                if (isinstance(n.value, ast.Call)
                                        and isinstance(n.value.func, ast.Name)
                                        and n.value.func.id in self._user_classes):
                                    return n.value.func.id
                                if (isinstance(n.value, ast.Name)
                                        and n.value.id in body_obj_classes):
                                    return body_obj_classes[n.value.id]
        # ClassName.classmethod(...) returning cls(...) or self — caller class
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in self._user_classes):
            class_name = node.func.value.id
            cls_info = self._user_classes[class_name]
            if cls_info.method_asts:
                m_ast = cls_info.method_asts.get(node.func.attr)
                if m_ast is not None:
                    for n in ast.walk(m_ast):
                        if not (isinstance(n, ast.Return) and n.value is not None):
                            continue
                        # `return cls(...)` or `return self`
                        if (isinstance(n.value, ast.Call)
                                and isinstance(n.value.func, ast.Name)
                                and n.value.func.id == "cls"):
                            return class_name
                        if (isinstance(n.value, ast.Name)
                                and n.value.id == "self"):
                            return class_name
        # Method call returning self/cls/ClassName(...): infer class from return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver_cls = self._infer_object_class(node.func.value)
            if receiver_cls is not None:
                cls_info = self._user_classes.get(receiver_cls)
                if cls_info and cls_info.method_asts:
                    m_ast = cls_info.method_asts.get(node.func.attr)
                    if m_ast is not None:
                        for n in ast.walk(m_ast):
                            if not (isinstance(n, ast.Return) and n.value is not None):
                                continue
                            if (isinstance(n.value, ast.Name)
                                    and n.value.id == "self"):
                                return receiver_cls
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Name)
                                    and n.value.func.id == "cls"):
                                return receiver_cls
                            # return ClassName(...) — new instance of that class
                            if (isinstance(n.value, ast.Call)
                                    and isinstance(n.value.func, ast.Name)
                                    and n.value.func.id in self._user_classes):
                                return n.value.func.id
        # Variable with known class
        if isinstance(node, ast.Name):
            if node.id == "self" and self._current_class:
                return self._current_class
            if node.id in self._obj_var_class:
                return self._obj_var_class[node.id]
        # Nested attribute access: obj.attr where attr is a known obj attr
        if isinstance(node, ast.Attribute):
            inner_cls = self._infer_object_class(node.value)
            if inner_cls:
                obj_types = self._class_obj_attr_types.get(inner_cls, {})
                if node.attr in obj_types:
                    return obj_types[node.attr]
        return None

    def _is_tuple_expr(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Tuple):
            return True
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, type_tag = self.variables[node.id]
            return type_tag == "tuple"
        # Function calls that return tuples
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "divmod":
                return True
            if name in self._user_functions:
                info = self._user_functions[name]
                if info.ret_tag == "ptr":
                    return True  # ptr return from user func = likely tuple
        # Method calls that return tuples
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if self._method_returns_tuple(node.func.value, node.func.attr):
                return True
        return False

    def _is_int_keyed_dict(self, node: ast.expr) -> bool:
        """Check if a dict expression uses integer keys (from dict comp with
        int iterator, dict literal with int keys, or subscript-store with
        int keys)."""
        if isinstance(node, ast.DictComp):
            # {i: ... for i in range(...)} → int keys
            if (isinstance(node.generators[0].iter, ast.Call)
                    and isinstance(node.generators[0].iter.func, ast.Name)
                    and node.generators[0].iter.func.id == "range"):
                return True
        if isinstance(node, ast.Dict) and node.keys:
            return all(isinstance(k, ast.Constant) and isinstance(k.value, int)
                       and not isinstance(k.value, bool)
                       for k in node.keys if k is not None)
        if isinstance(node, ast.Name):
            # Check via _csa_root_tree for the binding
            tree = getattr(self, "_csa_root_tree", None)
            if tree is not None:
                for n in ast.walk(tree):
                    if (isinstance(n, ast.Assign)
                            and len(n.targets) == 1
                            and isinstance(n.targets[0], ast.Name)
                            and n.targets[0].id == node.id):
                        return self._is_int_keyed_dict(n.value)
        return False

    def _is_dict_expr(self, node: ast.expr) -> bool:
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return True
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, type_tag = self.variables[node.id]
            return type_tag == "dict"
        # Function calls that return dicts
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "dict":
                return True
            if name in self._user_functions:
                return self._user_functions[name].ret_tag == "dict"
        # Object attribute access: obj.attr where attr is a dict
        if isinstance(node, ast.Attribute):
            obj_cls = self._infer_object_class(node.value)
            if obj_cls and obj_cls in self._class_container_attrs:
                _, dict_attrs = self._class_container_attrs[obj_cls]
                if node.attr in dict_attrs:
                    return True
        # Indexing a list of dicts or dict-of-dicts returns a dict
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            if self._is_list_expr(node.value):
                elem_type = self._get_list_elem_type(node.value)
                if elem_type == "dict":
                    return True
            if (isinstance(node.value, ast.Name)
                    and node.value.id in self._dict_var_dict_values):
                return True
            # Recursive: d["a"]["b"] where d["a"] is itself a dict
            # Walk up the subscript chain to find the base Name variable.
            if isinstance(node.value, ast.Subscript):
                base = node.value
                while isinstance(base, ast.Subscript):
                    base = base.value
                if (isinstance(base, ast.Name)
                        and base.id in self._dict_var_dict_values):
                    return True
        # Method calls that return dicts
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if self._method_returns_dict(node.func.value, node.func.attr):
                return True
        # Dict merge: dict | dict → new dict
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
                and self._is_dict_expr(node.left) and self._is_dict_expr(node.right)):
            return True
        return False

    def _emit_write_single(self, node: ast.expr) -> None:
        """Emit a write (no newline) for a single expression via FV dispatch."""
        fv = self._load_or_wrap_fv(node)
        tag, data = self._fv_unpack(fv)
        self.builder.call(self.runtime["fv_write"], [tag, data])

    def _is_pyobj_var(self, node: ast.expr) -> bool:
        """Check if an expression is a pyobj-tagged variable."""
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, tag = self.variables[node.id]
            return tag == "pyobj"
        return False

    def _is_fv_float_var(self, node: ast.expr) -> bool:
        """Check if an expression is a variable backed by an FpyValue that
        might hold a float (e.g. result of CPython bridge call)."""
        if not isinstance(node, ast.Name):
            # Direct CPython method call in expression: math.sqrt(9)+1
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                recv = node.func.value
                if (isinstance(recv, ast.Name)
                        and recv.id in self.variables
                        and self.variables[recv.id][1] == "pyobj"):
                    return True
            return False
        if node.id not in self.variables:
            return False
        # Check if variable was marked as from CPython bridge
        return node.id in getattr(self, '_cpython_result_vars', set())

    def _maybe_unwrap_fv_float(self, val: ir.Value,
                                node: ast.expr) -> ir.Value:
        """If a value comes from an FV-backed variable that might hold a float
        (e.g. from CPython bridge), check the runtime tag and bitcast to double.
        Returns the value unchanged if it's not an FV float."""
        if not self._USE_FV_LOCALS:
            return val
        if not (isinstance(val.type, ir.IntType) and val.type.width == 64):
            return val
        if not isinstance(node, ast.Name):
            return val
        if node.id not in self.variables:
            return val
        alloca, tag = self.variables[node.id]
        if not (isinstance(alloca.type, ir.PointerType)
                and alloca.type.pointee is fpy_val):
            return val
        # Load the FV and check if tag is FLOAT
        fv = self.builder.load(alloca)
        fv_tag = self.builder.extract_value(fv, 0)
        is_float = self.builder.icmp_signed(
            "==", fv_tag, ir.Constant(i32, FPY_TAG_FLOAT))
        float_val = self.builder.bitcast(val, double)
        # If float, return double; otherwise return original i64.
        # To unify the return type, convert the double path to i64 and
        # let the caller handle both. Actually, for arithmetic we need to
        # branch: if either operand is float, do float arithmetic.
        # Return a sentinel — use select to bitcast when float.
        # Since we can't change the type at runtime, tag this for the caller.
        return val  # caller must handle via _check_fv_float_operands

    def _convert_pyobj_to_numeric(self, val: ir.Value,
                                   node: ast.expr) -> ir.Value:
        """Convert a pyobj-tagged variable to a numeric value for arithmetic.
        Returns a double (converting int→double via sitofp, float→double
        via bitcast from the FpyValue data)."""
        if isinstance(val.type, ir.PointerType):
            # pyobj variable — convert through bridge to FpyValue
            tag_a = self._create_entry_alloca(i32, "py2num.tag")
            data_a = self._create_entry_alloca(i64, "py2num.data")
            self.builder.call(self.runtime["cpython_to_fv"],
                              [val, tag_a, data_a])
            tag = self.builder.load(tag_a)
            data = self.builder.load(data_a)
            is_float = self.builder.icmp_signed(
                "==", tag, ir.Constant(i32, FPY_TAG_FLOAT))
            float_val = self.builder.bitcast(data, double)
            int_as_float = self.builder.sitofp(data, double)
            return self.builder.select(is_float, float_val, int_as_float)
        return None  # not a pyobj

    def _emit_binop(self, node: ast.BinOp) -> ir.Value:
        """Emit a binary operation and return the LLVM value."""
        left = self._emit_expr_value(node.left)
        right = self._emit_expr_value(node.right)

        # Pyobj operands: convert through CPython bridge to numeric
        left_is_pyobj = isinstance(left.type, ir.PointerType) and self._is_pyobj_var(node.left)
        right_is_pyobj = isinstance(right.type, ir.PointerType) and self._is_pyobj_var(node.right)
        if left_is_pyobj or right_is_pyobj:
            if left_is_pyobj:
                left_d = self._convert_pyobj_to_numeric(left, node.left)
            elif isinstance(left.type, ir.DoubleType):
                left_d = left
            elif isinstance(left.type, ir.IntType):
                left_d = self.builder.sitofp(left, double)
            else:
                left_d = None
            if right_is_pyobj:
                right_d = self._convert_pyobj_to_numeric(right, node.right)
            elif isinstance(right.type, ir.DoubleType):
                right_d = right
            elif isinstance(right.type, ir.IntType):
                right_d = self.builder.sitofp(right, double)
            else:
                right_d = None
            if left_d is not None and right_d is not None:
                if isinstance(node.op, ast.Add):
                    return self.builder.fadd(left_d, right_d)
                elif isinstance(node.op, ast.Sub):
                    return self.builder.fsub(left_d, right_d)
                elif isinstance(node.op, ast.Mult):
                    return self.builder.fmul(left_d, right_d)
                elif isinstance(node.op, ast.Div):
                    return self.builder.fdiv(left_d, right_d)

        # FV float operands: if either side is from a CPython bridge result
        # (FV-backed variable that might hold float), check the runtime tag
        # and convert to float arithmetic.
        if (isinstance(left.type, ir.IntType) and left.type.width == 64
                and isinstance(right.type, ir.IntType) and right.type.width == 64):
            left_fv_float = self._is_fv_float_var(node.left)
            right_fv_float = self._is_fv_float_var(node.right)
            if left_fv_float or right_fv_float:
                if left_fv_float:
                    left_d = self.builder.bitcast(left, double)
                else:
                    left_d = self.builder.sitofp(left, double)
                if right_fv_float:
                    right_d = self.builder.bitcast(right, double)
                else:
                    right_d = self.builder.sitofp(right, double)
                if isinstance(node.op, ast.Add):
                    return self.builder.fadd(left_d, right_d)
                elif isinstance(node.op, ast.Sub):
                    return self.builder.fsub(left_d, right_d)
                elif isinstance(node.op, ast.Mult):
                    return self.builder.fmul(left_d, right_d)
                elif isinstance(node.op, ast.Div):
                    return self.builder.fdiv(left_d, right_d)

        # Object operator overloading: obj + obj → __add__, etc.
        if (isinstance(left.type, ir.PointerType) and isinstance(right.type, ir.PointerType)
                and self._is_obj_expr(node.left)):
            op_methods = {
                ast.Add: "__add__", ast.Sub: "__sub__", ast.Mult: "__mul__",
                ast.FloorDiv: "__floordiv__", ast.Div: "__truediv__",
                ast.Mod: "__mod__", ast.Pow: "__pow__",
            }
            method_name = op_methods.get(type(node.op))
            if method_name:
                name_ptr = self._make_string_constant(method_name)
                right_as_i64 = self.builder.ptrtoint(right, i64)
                result = self.builder.call(
                    self.runtime["obj_call_method1"], [left, name_ptr, right_as_i64])
                # The method likely returns an object pointer as i64
                return self.builder.inttoptr(result, i8_ptr)

        # Dict merge: dict | dict → new merged dict
        if (isinstance(node.op, ast.BitOr)
                and isinstance(left.type, ir.PointerType)
                and isinstance(right.type, ir.PointerType)
                and self._is_dict_expr(node.left) and self._is_dict_expr(node.right)):
            return self.builder.call(self.runtime["dict_merge"], [left, right])

        # Set operations (dict-backed sets): O(n) with O(1) per-element lookup
        if (isinstance(left.type, ir.PointerType) and isinstance(right.type, ir.PointerType)
                and (self._is_set_expr(node.left) or self._is_set_expr(node.right))):
            if isinstance(node.op, ast.BitOr):
                return self.builder.call(self.runtime["set_union"], [left, right])
            elif isinstance(node.op, ast.BitAnd):
                return self.builder.call(self.runtime["set_intersection"], [left, right])
            elif isinstance(node.op, ast.Sub):
                return self.builder.call(self.runtime["set_difference"], [left, right])
            elif isinstance(node.op, ast.BitXor):
                return self.builder.call(self.runtime["set_symmetric_diff"], [left, right])

        # List concatenation: list + list. Detect mismatched pointer types
        # (e.g. list + str) and raise TypeError at runtime instead of
        # crashing in list_concat.
        if (isinstance(left.type, ir.PointerType) and isinstance(right.type, ir.PointerType)
                and isinstance(node.op, ast.Add)
                and (self._is_list_expr(node.left) or self._is_list_expr(node.right))):
            left_type = self._known_pointer_type(node.left)
            right_type = self._known_pointer_type(node.right)
            if left_type == "list" and right_type is not None and right_type != "list":
                return self._emit_type_error(
                    f'can only concatenate list (not "{right_type}") to list',
                    node)
            if right_type == "list" and left_type is not None and left_type != "list":
                return self._emit_type_error(
                    f'unsupported operand type(s) for +: "{left_type}" and "list"',
                    node)
            return self.builder.call(self.runtime["list_concat"], [left, right])

        # List repetition: list * int or int * list
        if isinstance(node.op, ast.Mult):
            if isinstance(left.type, ir.PointerType) and self._is_list_expr(node.left) and isinstance(right.type, ir.IntType):
                return self.builder.call(self.runtime["list_repeat"], [left, right])
            if isinstance(right.type, ir.PointerType) and self._is_list_expr(node.right) and isinstance(left.type, ir.IntType):
                return self.builder.call(self.runtime["list_repeat"], [right, left])

        # String operations (only if NOT lists)
        if isinstance(left.type, ir.PointerType) and not self._is_list_expr(node.left):
            if isinstance(node.op, ast.Add) and isinstance(right.type, ir.PointerType):
                return self.builder.call(self.runtime["str_concat"], [left, right])
            elif isinstance(node.op, ast.Mult) and isinstance(right.type, ir.IntType):
                # string * int = repeat
                return self.builder.call(self.runtime["str_repeat"], [left, right])
            elif isinstance(node.op, ast.Mod):
                # fmt % args — build an args list if not already a list/tuple
                if self._is_list_expr(node.right) or self._is_tuple_expr(node.right):
                    args_list = right
                else:
                    # Wrap single value into a list
                    args_list = self.builder.call(self.runtime["list_new"], [])
                    self._emit_list_append_value(args_list, right)
                return self.builder.call(self.runtime["str_format_percent"], [left, args_list])
        if isinstance(right.type, ir.PointerType) and isinstance(node.op, ast.Mult):
            if isinstance(left.type, ir.IntType):
                # int * string = repeat
                return self.builder.call(self.runtime["str_repeat"], [right, left])

        # Type mismatch guard — if types don't match after all special cases
        if left.type != right.type:
            # Float promotion (only if the other side is also numeric)
            if (isinstance(left.type, ir.DoubleType) and isinstance(right.type, ir.IntType)):
                right = self.builder.sitofp(right, double)
                return self._emit_float_binop(node.op, left, right, node)
            if (isinstance(right.type, ir.DoubleType) and isinstance(left.type, ir.IntType)):
                left = self.builder.sitofp(left, double)
                return self._emit_float_binop(node.op, left, right, node)
            raise CodeGenError(
                f"Unsupported operand types for {type(node.op).__name__}: "
                f"{left.type} and {right.type}", node)

        # Type promotion: if either is double, promote both to double
        if isinstance(left.type, ir.DoubleType) or isinstance(right.type, ir.DoubleType):
            if isinstance(left.type, ir.IntType):
                left = self.builder.sitofp(left, double)
            if isinstance(right.type, ir.IntType):
                right = self.builder.sitofp(right, double)
            return self._emit_float_binop(node.op, left, right, node)
        else:
            return self._emit_int_binop(node.op, left, right, node)

    def _emit_int_binop(
        self, op: ast.operator, left: ir.Value, right: ir.Value, node: ast.AST
    ) -> ir.Value:
        """Emit an integer binary operation."""
        if isinstance(op, ast.Add):
            return self.builder.add(left, right)
        elif isinstance(op, ast.Sub):
            return self.builder.sub(left, right)
        elif isinstance(op, ast.Mult):
            return self.builder.mul(left, right)
        elif isinstance(op, ast.FloorDiv):
            return self._emit_python_floordiv(left, right)
        elif isinstance(op, ast.Mod):
            return self._emit_python_mod(left, right)
        elif isinstance(op, ast.Pow):
            return self.builder.call(self.runtime["pow_int"], [left, right])
        elif isinstance(op, ast.Div):
            # Python's / always returns float, even for ints. Use the
            # int-flavored safe division so the ZeroDivisionError message
            # matches CPython ("division by zero" for int/int, "float
            # division by zero" only when a float operand is involved).
            return self.builder.call(self.runtime["safe_int_fdiv"], [left, right])
        elif isinstance(op, ast.BitAnd):
            return self.builder.and_(left, right)
        elif isinstance(op, ast.BitOr):
            return self.builder.or_(left, right)
        elif isinstance(op, ast.BitXor):
            return self.builder.xor(left, right)
        elif isinstance(op, ast.LShift):
            return self.builder.shl(left, right)
        elif isinstance(op, ast.RShift):
            return self.builder.ashr(left, right)
        else:
            raise CodeGenError(f"Unsupported int operator: {type(op).__name__}", node)

    def _emit_python_floordiv(self, left: ir.Value, right: ir.Value) -> ir.Value:
        """
        Python-style floor division: rounds toward negative infinity.
        C's sdiv truncates toward zero. We correct by:
          q = trunc(left / right)
          r = left - q * right
          if r != 0 and (r ^ right) < 0: q -= 1
        """
        q = self.builder.call(self.runtime["safe_div"], [left, right])
        r = self.builder.srem(left, right)  # srem is safe when sdiv doesn't crash
        zero = ir.Constant(i64, 0)
        one = ir.Constant(i64, 1)

        # Check if remainder is nonzero
        r_nonzero = self.builder.icmp_signed("!=", r, zero)
        # Check if remainder and divisor have different signs (XOR < 0)
        r_xor_right = self.builder.xor(r, right)
        signs_differ = self.builder.icmp_signed("<", r_xor_right, zero)
        # Need adjustment if both conditions are true
        needs_adjust = self.builder.and_(r_nonzero, signs_differ)
        adjusted = self.builder.sub(q, one)
        return self.builder.select(needs_adjust, adjusted, q)

    def _emit_python_mod(self, left: ir.Value, right: ir.Value) -> ir.Value:
        """
        Python-style modulo: result has the sign of the divisor.
        C's srem result has the sign of the dividend. We correct by:
          r = left % right (C-style)
          if r != 0 and (r ^ right) < 0: r += right
        """
        r = self.builder.srem(left, right)
        zero = ir.Constant(i64, 0)

        r_nonzero = self.builder.icmp_signed("!=", r, zero)
        r_xor_right = self.builder.xor(r, right)
        signs_differ = self.builder.icmp_signed("<", r_xor_right, zero)
        needs_adjust = self.builder.and_(r_nonzero, signs_differ)
        adjusted = self.builder.add(r, right)
        return self.builder.select(needs_adjust, adjusted, r)

    def _emit_float_binop(
        self, op: ast.operator, left: ir.Value, right: ir.Value, node: ast.AST
    ) -> ir.Value:
        """Emit a float binary operation."""
        if isinstance(op, ast.Add):
            return self.builder.fadd(left, right)
        elif isinstance(op, ast.Sub):
            return self.builder.fsub(left, right)
        elif isinstance(op, ast.Mult):
            return self.builder.fmul(left, right)
        elif isinstance(op, ast.FloorDiv):
            # Python's // on floats: divide (raising on /0) then floor
            result = self.builder.call(self.runtime["safe_fdiv"],
                                       [left, right])
            # Use intrinsic for floor
            floor_fn = self.module.declare_intrinsic("llvm.floor", [double])
            return self.builder.call(floor_fn, [result])
        elif isinstance(op, ast.Mod):
            return self.builder.frem(left, right)
        elif isinstance(op, ast.Div):
            return self.builder.call(self.runtime["safe_fdiv"],
                                     [left, right])
        elif isinstance(op, ast.Pow):
            return self.builder.call(self.runtime["pow_float"], [left, right])
        else:
            raise CodeGenError(f"Unsupported float operator: {type(op).__name__}", node)

    def _try_constant_fold(self, node: ast.expr) -> int | float | str | None:
        """Try to evaluate an expression at compile time. Returns None if not constant."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = self._try_constant_fold(node.operand)
            if isinstance(val, (int, float)):
                return -val
        if isinstance(node, ast.BinOp):
            left = self._try_constant_fold(node.left)
            right = self._try_constant_fold(node.right)
            if isinstance(left, int) and isinstance(right, int):
                try:
                    if isinstance(node.op, ast.Add): return left + right
                    if isinstance(node.op, ast.Sub): return left - right
                    if isinstance(node.op, ast.Mult): return left * right
                    if isinstance(node.op, ast.Pow): return left ** right
                    if isinstance(node.op, ast.FloorDiv) and right != 0: return left // right
                    if isinstance(node.op, ast.Mod) and right != 0: return left % right
                except (OverflowError, ValueError):
                    pass
        return None

    def _emit_expr_value(self, node: ast.expr) -> ir.Value:
        """Emit an expression and return its LLVM value."""
        # Try compile-time constant folding (handles BigInt like 2**100)
        if isinstance(node, ast.BinOp):
            folded = self._try_constant_fold(node)
            if folded is not None:
                return self._emit_constant_value(folded)

        if isinstance(node, ast.Constant):
            return self._emit_constant_value(node.value)
        elif isinstance(node, ast.Name):
            # Built-in constants
            if node.id == "NotImplemented":
                return ir.Constant(i64, 0)  # sentinel
            # Check if this is a lambda-assigned function name used as a value
            if node.id in self._user_functions and node.id not in self.variables:
                info = self._user_functions[node.id]
                return self.builder.ptrtoint(info.func, i64)
            return self._load_variable(node.id, node)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            # __neg__ on user-class objects
            if self._is_obj_expr(node.operand):
                obj_cls = self._infer_object_class(node.operand)
                if obj_cls and self._class_has_method(obj_cls, "__neg__"):
                    obj = self._emit_expr_value(node.operand)
                    if isinstance(obj.type, ir.IntType):
                        obj = self.builder.inttoptr(obj, i8_ptr)
                    name_ptr = self._make_string_constant("__neg__")
                    result = self.builder.call(
                        self.runtime["obj_call_method0"], [obj, name_ptr])
                    return self.builder.inttoptr(result, i8_ptr)
            operand = self._emit_expr_value(node.operand)
            if isinstance(operand.type, ir.IntType):
                return self.builder.neg(operand)
            elif isinstance(operand.type, ir.DoubleType):
                return self.builder.fneg(operand)
            raise CodeGenError("Unsupported unary operand type", node)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return self._emit_expr_value(node.operand)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            operand = self._emit_expr_value(node.operand)
            if isinstance(operand.type, ir.IntType):
                return self.builder.not_(operand)
            raise CodeGenError("~ requires an integer operand", node)
        elif isinstance(node, ast.BinOp):
            return self._emit_binop(node)
        elif isinstance(node, ast.Call):
            return self._emit_call_expr(node)
        elif isinstance(node, ast.Compare):
            cmp = self._emit_compare(node)
            return self.builder.zext(cmp, i32)
        elif isinstance(node, ast.BoolOp):
            # BoolOp returns operand value (not bool) per Python semantics
            return self._emit_boolop(node)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            cmp = self._emit_condition(node.operand)
            result = self.builder.not_(cmp)
            return self.builder.zext(result, i32)
        elif isinstance(node, ast.Subscript):
            return self._emit_subscript(node)
        elif isinstance(node, ast.JoinedStr):
            return self._emit_fstring(node)
        elif isinstance(node, ast.List):
            return self._emit_list_literal(node)
        elif isinstance(node, ast.Tuple):
            return self._emit_tuple_literal(node)
        elif isinstance(node, ast.ListComp):
            return self._emit_list_comprehension(node)
        elif isinstance(node, ast.Dict):
            return self._emit_dict_literal(node)
        elif isinstance(node, ast.IfExp):
            return self._emit_ifexp(node)
        elif isinstance(node, ast.NamedExpr):
            value = self._emit_expr_value(node.value)
            tag = self._llvm_type_tag(value)
            self._store_variable(node.target.id, value, tag)
            return value
        elif isinstance(node, ast.Attribute):
            # type(X).__name__ pattern: return the type name (or metaclass)
            if (node.attr == "__name__"
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "type"
                    and len(node.value.args) == 1
                    and isinstance(node.value.args[0], ast.Name)):
                target = node.value.args[0].id
                metaclasses = getattr(self, '_class_metaclasses', {})
                if target in metaclasses:
                    return self._make_string_constant(metaclasses[target])
                elif target in self._user_classes:
                    return self._make_string_constant(target)
                # FV-backed variable: resolve by runtime tag
                elif (self._USE_FV_LOCALS
                        and target in self.variables):
                    alloca, tag = self.variables[target]
                    if (isinstance(alloca.type, ir.PointerType)
                            and alloca.type.pointee is fpy_val):
                        fv = self.builder.load(alloca)
                        fv_tag = self.builder.extract_value(fv, 0)
                        type_names = {
                            FPY_TAG_INT: "int", FPY_TAG_FLOAT: "float",
                            FPY_TAG_STR: "str", FPY_TAG_BOOL: "bool",
                            FPY_TAG_NONE: "NoneType", FPY_TAG_LIST: "list",
                            FPY_TAG_DICT: "dict",
                        }
                        result_alloca = self._create_entry_alloca(
                            i8_ptr, "typename")
                        default = self._make_string_constant("object")
                        self.builder.store(default, result_alloca)
                        for tv, tn in type_names.items():
                            is_m = self.builder.icmp_signed(
                                "==", fv_tag, ir.Constant(i32, tv))
                            s = self._make_string_constant(tn)
                            cur = self.builder.load(result_alloca)
                            self.builder.store(
                                self.builder.select(is_m, s, cur),
                                result_alloca)
                        return self.builder.load(result_alloca)
                else:
                    display = self._static_type_of(node.value.args[0])
                    return self._make_string_constant(display)
            # Native module attribute (e.g. math.pi): return constant
            if (isinstance(node.value, ast.Name)
                    and node.value.id in self.variables
                    and self.variables[node.value.id][1] == "native_mod"):
                result = self._emit_native_module_attr(
                    node.value.id, node.attr)
                if result is not None:
                    return result
            # CPython module attribute (e.g. os.sep): return as i8*
            # (PyObject*). Callers that need the FpyValue should use
            # _load_or_wrap_fv which does proper bridge conversion.
            if (isinstance(node.value, ast.Name)
                    and node.value.id in self.variables
                    and self.variables[node.value.id][1] == "pyobj"):
                obj = self._load_variable(node.value.id, node)
                if isinstance(obj.type, ir.IntType):
                    obj = self.builder.inttoptr(obj, i8_ptr)
                attr_name = self._make_string_constant(node.attr)
                return self.builder.call(
                    self.runtime["cpython_getattr"], [obj, attr_name])
            return self._emit_attr_load(node)
        elif isinstance(node, ast.Lambda):
            return self._emit_inline_lambda(node)
        elif isinstance(node, ast.DictComp):
            return self._emit_dict_comprehension(node)
        elif isinstance(node, ast.GeneratorExp):
            # Treat generator expressions as list comprehensions (eager)
            return self._emit_generator_as_list(node)
        elif isinstance(node, ast.Set):
            return self._emit_set_literal(node)
        elif isinstance(node, ast.Yield):
            # yield as expression (x = yield val) — emit the yield and
            # return None (send() not supported in simple generators)
            self._emit_yield(node)
            return ir.Constant(i64, 0)
        elif isinstance(node, ast.YieldFrom):
            self._emit_yield_from(node)
            return ir.Constant(i64, 0)
        elif isinstance(node, ast.SetComp):
            # Set comprehension: build as list, then convert to dict-backed set
            fake = ast.ListComp(elt=node.elt, generators=node.generators)
            ast.copy_location(fake, node)
            result = self._emit_list_comprehension(fake)
            return self.builder.call(self.runtime["set_from_list"], [result])
        else:
            raise CodeGenError(
                f"Unsupported expression: {type(node).__name__}", node
            )

    def _emit_call_expr(self, node: ast.Call) -> ir.Value:
        """Emit a function call as an expression (return value is used)."""
        if isinstance(node.func, ast.Name):
            name = node.func.id
            # Native module function (from math import sqrt → sqrt(x))
            if name in getattr(self, '_native_imports', {}):
                mod, attr = self._native_imports[name]
                result = self._emit_native_module_call(mod, attr, node)
                if result is not None:
                    return result
            # Check for closure variable
            if name in self.variables:
                _, tag = self.variables[name]
                if tag == "closure":
                    return self._emit_closure_call(node)
                if tag == "native_func":
                    # Native function via from-import — already handled above
                    pass
            if name in self._user_functions:
                result = self._emit_user_call(node)
                if result is None:
                    raise CodeGenError(
                        f"{name}() returns None, can't use as expression", node,
                    )
                return result
            if name in self._user_classes:
                return self._emit_constructor(node)
            if name == "len":
                return self._emit_builtin_len(node)
            if name == "isinstance":
                return self._emit_builtin_isinstance(node)
            if name == "type":
                if len(node.args) == 1:
                    # For FV-backed variables, check runtime tag to determine
                    # the actual type (handles CPython bridge results correctly)
                    arg_node = node.args[0]
                    if (self._USE_FV_LOCALS
                            and isinstance(arg_node, ast.Name)
                            and arg_node.id in self.variables):
                        alloca, tag = self.variables[arg_node.id]
                        if (isinstance(alloca.type, ir.PointerType)
                                and alloca.type.pointee is fpy_val):
                            fv = self.builder.load(alloca)
                            fv_tag = self.builder.extract_value(fv, 0)
                            # Build a runtime switch on tag
                            type_strs = {
                                FPY_TAG_INT: "<class 'int'>",
                                FPY_TAG_FLOAT: "<class 'float'>",
                                FPY_TAG_STR: "<class 'str'>",
                                FPY_TAG_BOOL: "<class 'bool'>",
                                FPY_TAG_NONE: "<class 'NoneType'>",
                                FPY_TAG_LIST: "<class 'list'>",
                                FPY_TAG_DICT: "<class 'dict'>",
                            }
                            result_alloca = self._create_entry_alloca(
                                i8_ptr, "type.result")
                            default_str = self._make_string_constant(
                                "<class 'object'>")
                            self.builder.store(default_str, result_alloca)
                            for tag_val, type_str in type_strs.items():
                                is_match = self.builder.icmp_signed(
                                    "==", fv_tag, ir.Constant(i32, tag_val))
                                str_ptr = self._make_string_constant(type_str)
                                current = self.builder.load(result_alloca)
                                selected = self.builder.select(
                                    is_match, str_ptr, current)
                                self.builder.store(selected, result_alloca)
                            return self.builder.load(result_alloca)
                    # Static type analysis fallback
                    actual = self._static_type_of(node.args[0])
                    # Also check for list/dict via type tags
                    if actual == "unknown":
                        if self._is_list_expr(node.args[0]):
                            actual = "list"
                        elif self._is_dict_expr(node.args[0]):
                            actual = "dict"
                    if actual == "unknown":
                        # Default: Python prints class name or type object
                        actual = "object"
                    type_name_map = {
                        "int": "int", "bool": "bool", "float": "float",
                        "str": "str", "list": "list", "dict": "dict",
                        "tuple": "tuple", "object": "object",
                    }
                    display = type_name_map.get(actual, actual)
                    return self._make_string_constant(f"<class '{display}'>")
                raise CodeGenError("type() with multiple args not supported", node)
            if name == "sorted":
                return self._emit_builtin_sorted(node)
            if name == "range":
                # range(stop) / range(start, stop) / range(start, stop, step) -> list
                if len(node.args) == 1:
                    start = ir.Constant(i64, 0)
                    stop = self._emit_expr_value(node.args[0])
                    step = ir.Constant(i64, 1)
                elif len(node.args) == 2:
                    start = self._emit_expr_value(node.args[0])
                    stop = self._emit_expr_value(node.args[1])
                    step = ir.Constant(i64, 1)
                elif len(node.args) == 3:
                    start = self._emit_expr_value(node.args[0])
                    stop = self._emit_expr_value(node.args[1])
                    step = self._emit_expr_value(node.args[2])
                else:
                    raise CodeGenError("range() takes 1-3 arguments", node)
                return self.builder.call(self.runtime["range"], [start, stop, step])
            if name == "list":
                # list(dict) → list of keys
                if len(node.args) == 1 and self._is_dict_expr(node.args[0]):
                    d = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["dict_keys"], [d])
                # list(x) — for now, just return the arg (shallow copy would be better)
                if len(node.args) == 1:
                    return self._emit_expr_value(node.args[0])
                if len(node.args) == 0:
                    return self.builder.call(self.runtime["list_new"], [])
                raise CodeGenError("list() with wrong number of args", node)
            if name == "dict":
                # dict() or dict([(k, v), ...])
                if len(node.args) == 0:
                    return self.builder.call(self.runtime["dict_new"], [])
                if len(node.args) == 1:
                    # dict([(k, v), ...]) — build dict by iterating
                    arg_node = node.args[0]
                    if isinstance(arg_node, ast.List):
                        # Build a dict from literal list of tuples at compile time
                        d = self.builder.call(self.runtime["dict_new"], [])
                        for elt in arg_node.elts:
                            if isinstance(elt, ast.Tuple) and len(elt.elts) == 2:
                                k_node, v_node = elt.elts
                                k_val = self._emit_expr_value(k_node)
                                v_val = self._emit_expr_value(v_node)
                                if not isinstance(k_val.type, ir.PointerType):
                                    raise CodeGenError("dict() key must be string", node)
                                tag, data = self._bare_to_tag_data(v_val, v_node)
                                self.builder.call(self.runtime["dict_set_fv"],
                                                  [d, k_val, ir.Constant(i32, tag), data])
                        return d
                    raise CodeGenError("dict() with non-literal argument not supported", node)
            if name == "tuple":
                # tuple(iter) — for our purposes, same as list()
                if len(node.args) == 1:
                    return self._emit_expr_value(node.args[0])
                if len(node.args) == 0:
                    return self.builder.call(self.runtime["list_new"], [])
                raise CodeGenError("tuple() with wrong number of args", node)
            if name == "reversed":
                if len(node.args) == 1:
                    arg = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["list_reversed"], [arg])
                raise CodeGenError("reversed() takes exactly one argument", node)
            if name == "int":
                if len(node.args) == 1:
                    arg_node = node.args[0]
                    # pyobj variable or CPython call expression:
                    # call Python's int() via bridge
                    is_pyobj_arg = self._is_pyobj_var(arg_node)
                    if not is_pyobj_arg and isinstance(arg_node, ast.Call):
                        # Check if it's a CPython method call: mod.func(...)
                        if isinstance(arg_node.func, ast.Attribute):
                            recv = arg_node.func.value
                            if (isinstance(recv, ast.Name)
                                    and recv.id in self.variables
                                    and self.variables[recv.id][1] == "pyobj"):
                                is_pyobj_arg = True
                    if is_pyobj_arg:
                        # Get the PyObject* result
                        if isinstance(arg_node, ast.Name):
                            ptr = self._load_variable(arg_node.id, arg_node)
                            if isinstance(ptr.type, ir.IntType):
                                ptr = self.builder.inttoptr(ptr, i8_ptr)
                        else:
                            ptr = self._emit_cpython_call_raw(arg_node)
                        # Call builtins.int(pyobj) through the bridge
                        blt = self._make_string_constant("builtins")
                        blt_mod = self.builder.call(
                            self.runtime["cpython_import"], [blt])
                        int_name = self._make_string_constant("int")
                        int_fn = self.builder.call(
                            self.runtime["cpython_getattr"], [blt_mod, int_name])
                        out_tag = self._create_entry_alloca(i32, "int.tag")
                        out_data = self._create_entry_alloca(i64, "int.data")
                        self.builder.call(self.runtime["cpython_call1"],
                                          [int_fn,
                                           ir.Constant(i32, FPY_TAG_OBJ),
                                           self.builder.ptrtoint(ptr, i64),
                                           out_tag, out_data])
                        return self.builder.load(out_data)
                    # FV-backed variables with runtime float tag
                    if (self._USE_FV_LOCALS
                            and isinstance(arg_node, ast.Name)
                            and arg_node.id in self.variables):
                        alloca, tag = self.variables[arg_node.id]
                        if (isinstance(alloca.type, ir.PointerType)
                                and alloca.type.pointee is fpy_val):
                            fv = self.builder.load(alloca)
                            fv_tag = self.builder.extract_value(fv, 0)
                            fv_data = self.builder.extract_value(fv, 1)
                            is_float = self.builder.icmp_signed(
                                "==", fv_tag, ir.Constant(i32, FPY_TAG_FLOAT))
                            float_val = self.builder.bitcast(fv_data, double)
                            int_from_float = self.builder.fptosi(float_val, i64)
                            return self.builder.select(
                                is_float, int_from_float, fv_data)
                    val = self._emit_expr_value(arg_node)
                    if isinstance(val.type, ir.DoubleType):
                        return self.builder.fptosi(val, i64)
                    if isinstance(val.type, ir.IntType) and val.type.width < 64:
                        return self.builder.zext(val, i64)
                    if isinstance(val.type, ir.PointerType):
                        # Might be pyobj or string
                        if (isinstance(arg_node, ast.Name)
                                and arg_node.id in self.variables
                                and self.variables[arg_node.id][1] == "pyobj"):
                            tag_a = self._create_entry_alloca(i32, "int.tag")
                            data_a = self._create_entry_alloca(i64, "int.data")
                            self.builder.call(self.runtime["cpython_to_fv"],
                                              [val, tag_a, data_a])
                            return self.builder.load(data_a)
                        return self.builder.call(self.runtime["str_to_int"], [val])
                    return val
                raise CodeGenError("int() with wrong number of args", node)
            if name == "map":
                if len(node.args) == 2:
                    return self._emit_builtin_map(node)
                raise CodeGenError("map() takes 2 arguments (function, iterable)", node)
            if name == "filter":
                if len(node.args) == 2:
                    return self._emit_builtin_filter(node)
                raise CodeGenError("filter() takes 2 arguments (function, iterable)", node)
            if name == "eval":
                if len(node.args) >= 1 and isinstance(node.args[0], ast.Constant):
                    # Literal string eval: compile via exec_get at runtime
                    expr_str = node.args[0].value
                    code = f"__eval_result__ = {expr_str}"
                    code_ptr = self._make_string_constant(code)
                    name_ptr = self._make_string_constant("__eval_result__")
                    result = self.builder.call(
                        self.runtime["cpython_exec_get"], [code_ptr, name_ptr])
                    # Convert the PyObject* result to native via bridge
                    out_tag = self._create_entry_alloca(i32, "eval.tag")
                    out_data = self._create_entry_alloca(i64, "eval.data")
                    self.builder.call(self.runtime["cpython_to_fv"],
                                      [result, out_tag, out_data])
                    return self.builder.load(out_data)
                if len(node.args) >= 1:
                    # Dynamic eval: route expression through CPython bridge
                    # Build code: __eval_result__ = eval(expr)
                    blt = self._make_string_constant("builtins")
                    blt_mod = self.builder.call(
                        self.runtime["cpython_import"], [blt])
                    eval_name = self._make_string_constant("eval")
                    eval_fn = self.builder.call(
                        self.runtime["cpython_getattr"], [blt_mod, eval_name])
                    arg = self._emit_expr_value(node.args[0])
                    tag, data = self._bare_to_tag_data(arg, node.args[0])
                    out_tag = self._create_entry_alloca(i32, "eval.tag")
                    out_data = self._create_entry_alloca(i64, "eval.data")
                    self.builder.call(self.runtime["cpython_call1"],
                                      [eval_fn,
                                       ir.Constant(i32, tag), data,
                                       out_tag, out_data])
                    return self.builder.load(out_data)
                raise CodeGenError("eval() requires at least 1 argument", node)
            if name == "enumerate":
                if len(node.args) >= 1:
                    lst = self._emit_expr_value(node.args[0])
                    start = None
                    if len(node.args) > 1:
                        start = self._emit_expr_value(node.args[1])
                    else:
                        # Accept start= kwarg
                        for kw in node.keywords:
                            if kw.arg == "start":
                                start = self._emit_expr_value(kw.value)
                                break
                    if start is None:
                        start = ir.Constant(i64, 0)
                    return self.builder.call(self.runtime["enumerate"], [lst, start])
                raise CodeGenError("enumerate() requires at least one argument", node)
            if name == "zip":
                if len(node.args) == 2:
                    a = self._emit_expr_value(node.args[0])
                    b = self._emit_expr_value(node.args[1])
                    return self.builder.call(self.runtime["zip"], [a, b])
                if len(node.args) == 3:
                    a = self._emit_expr_value(node.args[0])
                    b = self._emit_expr_value(node.args[1])
                    c = self._emit_expr_value(node.args[2])
                    return self.builder.call(self.runtime["zip3"], [a, b, c])
                raise CodeGenError("zip() with 1 or >3 args not yet supported", node)
            if name == "any":
                if len(node.args) == 1 and self._is_list_expr(node.args[0]):
                    lst = self._emit_expr_value(node.args[0])
                    length = self.builder.call(self.runtime["list_length"], [lst])
                    result_alloca = self._create_entry_alloca(ir.IntType(1), "any.result")
                    self.builder.store(ir.Constant(ir.IntType(1), 0), result_alloca)
                    idx_alloca = self._create_entry_alloca(i64, "any.idx")
                    self.builder.store(ir.Constant(i64, 0), idx_alloca)
                    cond_b = self._new_block("any.cond")
                    body_b = self._new_block("any.body")
                    end_b = self._new_block("any.end")
                    self.builder.branch(cond_b)
                    self.builder.position_at_end(cond_b)
                    idx = self.builder.load(idx_alloca)
                    self.builder.cbranch(self.builder.icmp_signed("<", idx, length), body_b, end_b)
                    self.builder.position_at_end(body_b)
                    idx = self.builder.load(idx_alloca)
                    elem = self._list_get_as_bare(lst, idx, "int")
                    is_true = self.builder.icmp_signed("!=", elem, ir.Constant(i64, 0))
                    found_b = self._new_block("any.found")
                    next_b = self._new_block("any.next")
                    self.builder.cbranch(is_true, found_b, next_b)
                    self.builder.position_at_end(found_b)
                    self.builder.store(ir.Constant(ir.IntType(1), 1), result_alloca)
                    self.builder.branch(end_b)
                    self.builder.position_at_end(next_b)
                    self.builder.store(self.builder.add(self.builder.load(idx_alloca), ir.Constant(i64, 1)), idx_alloca)
                    self.builder.branch(cond_b)
                    self.builder.position_at_end(end_b)
                    return self.builder.zext(self.builder.load(result_alloca), i32)
                raise CodeGenError("any() requires a list argument", node)
            if name == "all":
                if len(node.args) == 1 and self._is_list_expr(node.args[0]):
                    lst = self._emit_expr_value(node.args[0])
                    length = self.builder.call(self.runtime["list_length"], [lst])
                    result_alloca = self._create_entry_alloca(ir.IntType(1), "all.result")
                    self.builder.store(ir.Constant(ir.IntType(1), 1), result_alloca)
                    idx_alloca = self._create_entry_alloca(i64, "all.idx")
                    self.builder.store(ir.Constant(i64, 0), idx_alloca)
                    cond_b = self._new_block("all.cond")
                    body_b = self._new_block("all.body")
                    end_b = self._new_block("all.end")
                    self.builder.branch(cond_b)
                    self.builder.position_at_end(cond_b)
                    idx = self.builder.load(idx_alloca)
                    self.builder.cbranch(self.builder.icmp_signed("<", idx, length), body_b, end_b)
                    self.builder.position_at_end(body_b)
                    idx = self.builder.load(idx_alloca)
                    elem = self._list_get_as_bare(lst, idx, "int")
                    is_false = self.builder.icmp_signed("==", elem, ir.Constant(i64, 0))
                    fail_b = self._new_block("all.fail")
                    next_b = self._new_block("all.next")
                    self.builder.cbranch(is_false, fail_b, next_b)
                    self.builder.position_at_end(fail_b)
                    self.builder.store(ir.Constant(ir.IntType(1), 0), result_alloca)
                    self.builder.branch(end_b)
                    self.builder.position_at_end(next_b)
                    self.builder.store(self.builder.add(self.builder.load(idx_alloca), ir.Constant(i64, 1)), idx_alloca)
                    self.builder.branch(cond_b)
                    self.builder.position_at_end(end_b)
                    return self.builder.zext(self.builder.load(result_alloca), i32)
                raise CodeGenError("all() requires a list argument", node)
            if name == "bool":
                if len(node.args) == 1:
                    return self.builder.zext(self._truthiness_of_expr(node.args[0]), i32)
                raise CodeGenError("bool() takes exactly one argument", node)
            if name == "float":
                if len(node.args) == 1:
                    arg_node = node.args[0]
                    # pyobj: call Python's float() via bridge
                    if self._is_pyobj_var(arg_node):
                        ptr = self._load_variable(arg_node.id, arg_node)
                        if isinstance(ptr.type, ir.IntType):
                            ptr = self.builder.inttoptr(ptr, i8_ptr)
                        blt = self._make_string_constant("builtins")
                        blt_mod = self.builder.call(
                            self.runtime["cpython_import"], [blt])
                        float_name = self._make_string_constant("float")
                        float_fn = self.builder.call(
                            self.runtime["cpython_getattr"],
                            [blt_mod, float_name])
                        out_tag = self._create_entry_alloca(i32, "float.tag")
                        out_data = self._create_entry_alloca(i64, "float.data")
                        self.builder.call(self.runtime["cpython_call1"],
                                          [float_fn,
                                           ir.Constant(i32, FPY_TAG_OBJ),
                                           self.builder.ptrtoint(ptr, i64),
                                           out_tag, out_data])
                        data = self.builder.load(out_data)
                        return self.builder.bitcast(data, double)
                    val = self._emit_expr_value(arg_node)
                    if isinstance(val.type, ir.IntType):
                        return self.builder.sitofp(val, double)
                    if isinstance(val.type, ir.PointerType):
                        return self.builder.call(self.runtime["str_to_float"], [val])
                    return val
                raise CodeGenError("float() takes exactly one argument", node)
            if name == "str":
                if len(node.args) == 1:
                    # Use FV dispatch so runtime tag drives the conversion
                    # (e.g. dict values whose compile-time tag is wrong).
                    fv = self._load_or_wrap_fv(node.args[0])
                    return self._fv_call_str(fv)
                raise CodeGenError("str() takes exactly one argument", node)
            if name == "hash":
                if len(node.args) == 1:
                    arg_node = node.args[0]
                    if self._is_obj_expr(arg_node):
                        obj_cls = self._infer_object_class(arg_node)
                        if obj_cls and self._class_has_method(obj_cls, "__hash__"):
                            obj = self._emit_expr_value(arg_node)
                            if isinstance(obj.type, ir.IntType):
                                obj = self.builder.inttoptr(obj, i8_ptr)
                            name_ptr = self._make_string_constant("__hash__")
                            return self.builder.call(
                                self.runtime["obj_call_method0"],
                                [obj, name_ptr])
                    # Default: return id-like hash
                    val = self._emit_expr_value(arg_node)
                    return val
                raise CodeGenError("hash() takes exactly one argument", node)
            if name == "abs":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    if isinstance(val.type, ir.IntType):
                        neg = self.builder.neg(val)
                        is_neg = self.builder.icmp_signed("<", val, ir.Constant(i64, 0))
                        return self.builder.select(is_neg, neg, val)
                    elif isinstance(val.type, ir.DoubleType):
                        fabs_fn = self.module.declare_intrinsic("llvm.fabs", [double])
                        return self.builder.call(fabs_fn, [val])
                raise CodeGenError("abs() takes exactly one argument", node)
            if name == "divmod":
                if len(node.args) == 2:
                    a = self._emit_expr_value(node.args[0])
                    b = self._emit_expr_value(node.args[1])
                    q_alloca = self._create_entry_alloca(i64, "dm.q")
                    r_alloca = self._create_entry_alloca(i64, "dm.r")
                    self.builder.call(self.runtime["divmod"], [a, b, q_alloca, r_alloca])
                    q_val = self.builder.load(q_alloca)
                    r_val = self.builder.load(r_alloca)
                    # Build a 2-tuple for the result (via FV-ABI append)
                    tup = self.builder.call(self.runtime["tuple_new"], [])
                    int_tag = ir.Constant(i32, FPY_TAG_INT)
                    self.builder.call(self.runtime["list_append_fv"], [tup, int_tag, q_val])
                    self.builder.call(self.runtime["list_append_fv"], [tup, int_tag, r_val])
                    return tup
                raise CodeGenError("divmod() takes exactly 2 arguments", node)
            if name == "pow":
                if len(node.args) == 2:
                    b = self._emit_expr_value(node.args[0])
                    e = self._emit_expr_value(node.args[1])
                    if isinstance(b.type, ir.DoubleType) or isinstance(e.type, ir.DoubleType):
                        if isinstance(b.type, ir.IntType):
                            b = self.builder.sitofp(b, double)
                        if isinstance(e.type, ir.IntType):
                            e = self.builder.sitofp(e, double)
                        return self.builder.call(self.runtime["pow_float"], [b, e])
                    return self.builder.call(self.runtime["pow_int"], [b, e])
                if len(node.args) == 3:
                    b = self._emit_expr_value(node.args[0])
                    e = self._emit_expr_value(node.args[1])
                    m = self._emit_expr_value(node.args[2])
                    return self.builder.call(self.runtime["pow_mod"], [b, e, m])
                raise CodeGenError("pow() takes 2 or 3 arguments", node)
            if name == "chr":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["chr"], [val])
                raise CodeGenError("chr() takes exactly one argument", node)
            if name == "ord":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["ord"], [val])
                raise CodeGenError("ord() takes exactly one argument", node)
            if name == "hex":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["hex"], [val])
                raise CodeGenError("hex() takes exactly one argument", node)
            if name == "oct":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["oct"], [val])
                raise CodeGenError("oct() takes exactly one argument", node)
            if name == "bin":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["bin"], [val])
                raise CodeGenError("bin() takes exactly one argument", node)
            if name == "round":
                if len(node.args) == 1:
                    val = self._emit_expr_value(node.args[0])
                    if isinstance(val.type, ir.IntType):
                        # round(int) = int
                        return val
                    return self.builder.call(self.runtime["round"], [val])
                if len(node.args) == 2:
                    val = self._emit_expr_value(node.args[0])
                    ndigits = self._emit_expr_value(node.args[1])
                    if isinstance(val.type, ir.IntType):
                        val = self.builder.sitofp(val, double)
                    return self.builder.call(self.runtime["round_ndigits"], [val, ndigits])
                raise CodeGenError("round() takes 1 or 2 arguments", node)
            if name == "repr":
                if len(node.args) == 1:
                    # Use FV dispatch so runtime tag drives the conversion.
                    fv = self._load_or_wrap_fv(node.args[0])
                    return self._fv_call_repr(fv)
                raise CodeGenError("repr() takes exactly one argument", node)
            if name == "sum":
                if len(node.args) >= 1 and self._is_list_expr(node.args[0]):
                    # Sum of a list — iterate and accumulate
                    lst = self._emit_expr_value(node.args[0])
                    length = self.builder.call(self.runtime["list_length"], [lst])
                    sum_alloca = self._create_entry_alloca(i64, "sum.acc")
                    # Optional start value
                    if len(node.args) >= 2:
                        start_val = self._emit_expr_value(node.args[1])
                        self.builder.store(start_val, sum_alloca)
                    else:
                        self.builder.store(ir.Constant(i64, 0), sum_alloca)
                    idx_alloca = self._create_entry_alloca(i64, "sum.idx")
                    self.builder.store(ir.Constant(i64, 0), idx_alloca)

                    cond_block = self._new_block("sum.cond")
                    body_block = self._new_block("sum.body")
                    end_block = self._new_block("sum.end")

                    self.builder.branch(cond_block)
                    self.builder.position_at_end(cond_block)
                    idx = self.builder.load(idx_alloca)
                    cond = self.builder.icmp_signed("<", idx, length)
                    self.builder.cbranch(cond, body_block, end_block)

                    self.builder.position_at_end(body_block)
                    idx = self.builder.load(idx_alloca)
                    elem = self._list_get_as_bare(lst, idx, "int")
                    acc = self.builder.load(sum_alloca)
                    self.builder.store(self.builder.add(acc, elem), sum_alloca)
                    self.builder.store(self.builder.add(idx, ir.Constant(i64, 1)), idx_alloca)
                    self.builder.branch(cond_block)

                    self.builder.position_at_end(end_block)
                    return self.builder.load(sum_alloca)
                raise CodeGenError("sum() requires a list argument", node)
            if name == "set":
                if len(node.args) == 1:
                    arg = self._emit_expr_value(node.args[0])
                    # Convert list to dict-backed set
                    return self.builder.call(self.runtime["set_from_list"], [arg])
                if len(node.args) == 0:
                    # Empty set: empty dict (dict-backed set)
                    return self.builder.call(self.runtime["dict_new"], [])
                raise CodeGenError("set() takes 0 or 1 arguments", node)
            if name == "min" or name == "max":
                # Extract key= kwarg if provided. Supports `key=len` (for
                # strings) and `key=<user_function>` that returns int.
                key_func_name: str | None = None
                key_func_ptr = None  # for lambda/closure keys
                for kw in node.keywords:
                    if kw.arg == "key":
                        if isinstance(kw.value, ast.Name):
                            key_func_name = kw.value.id
                        elif isinstance(kw.value, ast.Lambda):
                            # Compile lambda as i64(i64) function pointer
                            key_func_ptr = self._get_unary_func_ptr(kw.value, node)
                            key_func_name = "__lambda__"
                if len(node.args) == 1 and self._is_list_expr(node.args[0]):
                    lst = self._emit_expr_value(node.args[0])
                    length = self.builder.call(self.runtime["list_length"], [lst])
                    elem_type = self._get_list_elem_type(node.args[0])
                    is_str = (elem_type == "str")
                    result_type = i8_ptr if is_str else i64
                    result_alloca = self._create_entry_alloca(result_type, f"{name}.result")
                    first = self._list_get_as_bare(
                        lst, ir.Constant(i64, 0), "str" if is_str else "int")
                    self.builder.store(first, result_alloca)

                    def _apply_key(e):
                        """Apply the key function to an element, returning i64."""
                        if key_func_name is None:
                            return e
                        if key_func_name == "__lambda__":
                            # Call through function pointer
                            fn_typed = self.builder.bitcast(
                                key_func_ptr,
                                ir.PointerType(ir.FunctionType(i64, [i64])))
                            arg = e
                            if isinstance(e.type, ir.PointerType):
                                arg = self.builder.ptrtoint(e, i64)
                            return self.builder.call(fn_typed, [arg])
                        if key_func_name == "len":
                            # len on strings returns int64
                            if isinstance(e.type, ir.PointerType):
                                return self.builder.call(
                                    self.runtime["str_len"], [e])
                            if isinstance(e.type, ir.IntType):
                                return self.builder.call(
                                    self.runtime["list_length"], [
                                        self.builder.inttoptr(e, i8_ptr)])
                            return ir.Constant(i64, 0)
                        if key_func_name == "abs":
                            neg = self.builder.neg(e)
                            is_neg = self.builder.icmp_signed(
                                "<", e, ir.Constant(i64, 0))
                            return self.builder.select(is_neg, neg, e)
                        # User function call
                        if key_func_name in self._user_functions:
                            info = self._user_functions[key_func_name]
                            fv = self._wrap_arg_value(e, None)
                            ret = self.builder.call(info.func, [fv])
                            if info.uses_fv_abi:
                                return self._unwrap_return_value(ret, info)
                            return ret
                        return e

                    # Track the best *key value*, but return the original
                    # element. Store both key-of-best and best-element.
                    # Only create key_alloca when a key= was specified.
                    key_alloca = None
                    if key_func_name is not None:
                        key_alloca = self._create_entry_alloca(
                            i64, f"{name}.keybest")
                        first_key = _apply_key(first)
                        if first_key.type != i64:
                            if isinstance(first_key.type, ir.IntType):
                                first_key = self.builder.zext(first_key, i64)
                        self.builder.store(first_key, key_alloca)
                    idx_alloca = self._create_entry_alloca(i64, f"{name}.idx")
                    self.builder.store(ir.Constant(i64, 1), idx_alloca)

                    cond_block = self._new_block(f"{name}.cond")
                    body_block = self._new_block(f"{name}.body")
                    end_block = self._new_block(f"{name}.end")

                    self.builder.branch(cond_block)
                    self.builder.position_at_end(cond_block)
                    idx = self.builder.load(idx_alloca)
                    cond = self.builder.icmp_signed("<", idx, length)
                    self.builder.cbranch(cond, body_block, end_block)

                    self.builder.position_at_end(body_block)
                    idx = self.builder.load(idx_alloca)
                    current = self.builder.load(result_alloca)
                    if key_func_name is not None:
                        elem = self._list_get_as_bare(
                            lst, idx, "str" if is_str else "int")
                        elem_key = _apply_key(elem)
                        if elem_key.type != i64 and isinstance(elem_key.type, ir.IntType):
                            elem_key = self.builder.zext(elem_key, i64)
                        best_key = self.builder.load(key_alloca)
                        op = "<" if name == "min" else ">"
                        is_better = self.builder.icmp_signed(op, elem_key, best_key)
                        # Update best key and element
                        new_key = self.builder.select(is_better, elem_key, best_key)
                        self.builder.store(new_key, key_alloca)
                        new_elem = self.builder.select(is_better, elem, current)
                        self.builder.store(new_elem, result_alloca)
                    elif is_str:
                        elem = self._list_get_as_bare(lst, idx, "str")
                        cmp_result = self.builder.call(self.runtime["str_compare"], [elem, current])
                        op = "<" if name == "min" else ">"
                        is_better = self.builder.icmp_signed(op, cmp_result, ir.Constant(i64, 0))
                        new_val = self.builder.select(is_better, elem, current)
                        self.builder.store(new_val, result_alloca)
                    else:
                        elem = self._list_get_as_bare(lst, idx, "int")
                        op = "<" if name == "min" else ">"
                        is_better = self.builder.icmp_signed(op, elem, current)
                        new_val = self.builder.select(is_better, elem, current)
                        self.builder.store(new_val, result_alloca)
                    self.builder.store(self.builder.add(idx, ir.Constant(i64, 1)), idx_alloca)
                    self.builder.branch(cond_block)

                    self.builder.position_at_end(end_block)
                    return self.builder.load(result_alloca)
                if len(node.args) >= 2:
                    # min/max with multiple inline args: min(a, b, c, ...)
                    result = self._emit_expr_value(node.args[0])
                    op = "<" if name == "min" else ">"
                    for arg_node in node.args[1:]:
                        other = self._emit_expr_value(arg_node)
                        is_better = self.builder.icmp_signed(op, other, result)
                        result = self.builder.select(is_better, other, result)
                    return result
                raise CodeGenError(f"{name}() requires a list argument or multiple arguments", node)
        # Unknown builtins: route through CPython bridge
        # This handles bytearray(), frozenset(), slice(), complex(), etc.
        # Only for names that aren't local variables, user functions, or classes.
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if (name not in self._user_functions
                    and name not in self._user_classes
                    and name not in self.variables):
                # Not a user function or class — try CPython bridge
                builtin_name = self._make_string_constant("builtins")
                builtins_mod = self.builder.call(
                    self.runtime["cpython_import"], [builtin_name])
                func_name = self._make_string_constant(name)
                callable_ptr = self.builder.call(
                    self.runtime["cpython_getattr"],
                    [builtins_mod, func_name])
                out_tag = self._create_entry_alloca(i32, "pyblt.tag")
                out_data = self._create_entry_alloca(i64, "pyblt.data")
                n_args = len(node.args)
                if n_args == 0:
                    self.builder.call(self.runtime["cpython_call0"],
                                      [callable_ptr, out_tag, out_data])
                elif n_args == 1:
                    arg = self._emit_expr_value(node.args[0])
                    tag, data = self._bare_to_tag_data(arg, node.args[0])
                    self.builder.call(self.runtime["cpython_call1"],
                                      [callable_ptr,
                                       ir.Constant(i32, tag), data,
                                       out_tag, out_data])
                elif n_args == 2:
                    a1 = self._emit_expr_value(node.args[0])
                    t1, d1 = self._bare_to_tag_data(a1, node.args[0])
                    a2 = self._emit_expr_value(node.args[1])
                    t2, d2 = self._bare_to_tag_data(a2, node.args[1])
                    self.builder.call(self.runtime["cpython_call2"],
                                      [callable_ptr,
                                       ir.Constant(i32, t1), d1,
                                       ir.Constant(i32, t2), d2,
                                       out_tag, out_data])
                else:
                    raise CodeGenError(
                        f"CPython bridge call with {n_args} args not supported",
                        node)
                data = self.builder.load(out_data)
                return data

        # Method calls like s.lower(), obj.speak()
        if isinstance(node.func, ast.Attribute):
            # Native module call: math.sqrt(x) → direct C libm call
            if (isinstance(node.func.value, ast.Name)
                    and node.func.value.id in self.variables
                    and self.variables[node.func.value.id][1] == "native_mod"):
                result = self._emit_native_module_call(
                    node.func.value.id, node.func.attr, node)
                if result is not None:
                    return result

            # CPython module method call: os.getcwd(), json.dumps(x), etc.
            # Check if the receiver is a pyobj variable or a chained
            # attribute access on a pyobj (e.g. os.path → Attribute on os).
            receiver_is_pyobj = False
            if (isinstance(node.func.value, ast.Name)
                    and node.func.value.id in self.variables
                    and self.variables[node.func.value.id][1] == "pyobj"):
                receiver_is_pyobj = True
            elif (isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id in self.variables
                    and self.variables[node.func.value.value.id][1] == "pyobj"):
                receiver_is_pyobj = True
            if receiver_is_pyobj:
                fv = self._emit_cpython_method_call(node)
                # Unwrap the FpyValue to a bare type based on the tag
                tag = self.builder.extract_value(fv, 0)
                data = self.builder.extract_value(fv, 1)
                # For expression context, return the data as the most
                # likely type. Check tag at runtime for float vs int.
                is_float = self.builder.icmp_signed(
                    "==", tag, ir.Constant(i32, FPY_TAG_FLOAT))
                float_val = self.builder.bitcast(data, double)
                int_val = data
                # If the caller needs a specific type, they'll cast.
                # Default: return as double if float, else i64.
                return self.builder.select(
                    is_float, self.builder.bitcast(float_val, i64), int_val)
            return self._emit_method_call(node)
        # Direct pyobj call: func(args) where func is pyobj-tagged
        if (isinstance(node.func, ast.Name)
                and node.func.id in self.variables
                and self.variables[node.func.id][1] == "pyobj"):
            fv = self._emit_cpython_direct_call_expr(node)
            data = self.builder.extract_value(fv, 1)
            return data
        # __call__ on user-class objects
        if isinstance(node.func, ast.Name) and node.func.id in self.variables:
            _, tag = self.variables[node.func.id]
            if tag == "obj":
                obj_cls = self._obj_var_class.get(node.func.id)
                if obj_cls and self._class_has_method(obj_cls, "__call__"):
                    obj = self._load_variable(node.func.id, node)
                    if isinstance(obj.type, ir.IntType):
                        obj = self.builder.inttoptr(obj, i8_ptr)
                    name_ptr = self._make_string_constant("__call__")
                    if len(node.args) == 0:
                        return self.builder.call(
                            self.runtime["obj_call_method0"],
                            [obj, name_ptr])
                    elif len(node.args) == 1:
                        a = self._emit_expr_value(node.args[0])
                        if isinstance(a.type, ir.PointerType):
                            a = self.builder.ptrtoint(a, i64)
                        elif isinstance(a.type, ir.IntType) and a.type.width != 64:
                            a = self.builder.zext(a, i64)
                        return self.builder.call(
                            self.runtime["obj_call_method1"],
                            [obj, name_ptr, a])
                    elif len(node.args) == 2:
                        a1 = self._emit_expr_value(node.args[0])
                        a2 = self._emit_expr_value(node.args[1])
                        if isinstance(a1.type, ir.IntType) and a1.type.width != 64:
                            a1 = self.builder.zext(a1, i64)
                        if isinstance(a2.type, ir.IntType) and a2.type.width != 64:
                            a2 = self.builder.zext(a2, i64)
                        return self.builder.call(
                            self.runtime["obj_call_method2"],
                            [obj, name_ptr, a1, a2])
        # Call-on-Call: C()(5) — the result of C() is an object with __call__
        if isinstance(node.func, ast.Call):
            callee = self._emit_expr_value(node.func)
            if isinstance(callee.type, ir.IntType):
                callee = self.builder.inttoptr(callee, i8_ptr)
            if isinstance(callee.type, ir.PointerType):
                name_ptr = self._make_string_constant("__call__")
                if len(node.args) == 0:
                    return self.builder.call(
                        self.runtime["obj_call_method0"],
                        [callee, name_ptr])
                elif len(node.args) == 1:
                    a = self._emit_expr_value(node.args[0])
                    if isinstance(a.type, ir.PointerType):
                        a = self.builder.ptrtoint(a, i64)
                    elif isinstance(a.type, ir.IntType) and a.type.width != 64:
                        a = self.builder.zext(a, i64)
                    return self.builder.call(
                        self.runtime["obj_call_method1"],
                        [callee, name_ptr, a])
        # Last resort: try calling as a closure (for higher-order function params)
        if isinstance(node.func, ast.Name) and node.func.id in self.variables:
            return self._emit_closure_call(node)
        raise CodeGenError(
            f"Unsupported function call in expression: {ast.dump(node.func)}",
            node,
        )

    def _emit_builtin_map(self, node: ast.Call) -> ir.Value:
        """Emit map(func, iterable) as an inline loop.

        Emits a new list and iterates the input, calling func on each element
        and appending the result with proper FpyValue tagging. This handles
        functions that return different types (str, int, float, etc.) unlike
        the old list_map_int which hardcoded INT tags.
        """
        fn_node = node.args[0]
        seq = self._emit_expr_value(node.args[1])
        result = self.builder.call(self.runtime["list_new"], [])
        length = self.builder.call(self.runtime["list_length"], [seq])

        idx_alloca = self._create_entry_alloca(i64, "map.idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = self._new_block("map.cond")
        body_block = self._new_block("map.body")
        end_block = self._new_block("map.end")

        self.builder.branch(cond_block)
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, length)
        self.builder.cbranch(cond, body_block, end_block)

        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)
        # Get element as bare value (int for int lists, str for str lists)
        elem_tag_a = self._create_entry_alloca(i32, "map.etag")
        elem_data_a = self._create_entry_alloca(i64, "map.edata")
        self.builder.call(self.runtime["list_get_fv"],
                          [seq, idx, elem_tag_a, elem_data_a])
        elem_data = self.builder.load(elem_data_a)

        # Call the function on the element
        # Determine what the function is and how to call it
        if isinstance(fn_node, ast.Name) and fn_node.id == "str":
            # str(x) — use int_to_str for ints, passthrough for strings
            str_val = self.builder.call(self.runtime["int_to_str"], [elem_data])
            self.builder.call(self.runtime["list_append_fv"],
                              [result, ir.Constant(i32, FPY_TAG_STR),
                               self.builder.ptrtoint(str_val, i64)])
        elif isinstance(fn_node, ast.Name) and fn_node.id == "int":
            self.builder.call(self.runtime["list_append_fv"],
                              [result, ir.Constant(i32, FPY_TAG_INT), elem_data])
        elif isinstance(fn_node, ast.Name) and fn_node.id == "float":
            self.builder.call(self.runtime["list_append_fv"],
                              [result, ir.Constant(i32, FPY_TAG_FLOAT), elem_data])
        else:
            # General case: get function pointer and call via call_ptr1
            # (which auto-detects closures via magic number)
            fn_ptr = self._get_unary_func_ptr(fn_node, node)
            mapped = self.builder.call(
                self.runtime["call_ptr1"], [fn_ptr, elem_data])
            # Infer result tag from the function
            if isinstance(fn_node, ast.Lambda):
                # Lambda body type determines the tag
                body = fn_node.body
                if (isinstance(body, ast.Compare)
                        or isinstance(body, ast.BoolOp)):
                    tag = FPY_TAG_BOOL
                else:
                    tag = FPY_TAG_INT
            elif (isinstance(fn_node, ast.Name)
                    and fn_node.id in self._user_functions):
                info = self._user_functions[fn_node.id]
                if info.ret_tag == "str":
                    tag = FPY_TAG_STR
                elif info.ret_tag == "float":
                    tag = FPY_TAG_FLOAT
                else:
                    tag = FPY_TAG_INT
            else:
                tag = FPY_TAG_INT
            self.builder.call(self.runtime["list_append_fv"],
                              [result, ir.Constant(i32, tag), mapped])

        next_idx = self.builder.add(
            self.builder.load(idx_alloca), ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        self.builder.position_at_end(end_block)
        return result

    def _emit_native_module_call(self, mod_name: str, func_name: str,
                                  node: ast.Call) -> ir.Value | None:
        """Emit a native module function call (e.g. math.sqrt(x)).
        Returns the result value, or None if the function isn't natively supported."""
        if mod_name in self._NATIVE_MODULES:
            # math module
            if func_name in self._MATH_FUNCTIONS:
                rt_key, n_expected = self._MATH_FUNCTIONS[func_name]
                if len(node.args) == n_expected:
                    args = []
                    for arg_node in node.args:
                        val = self._emit_expr_value(arg_node)
                        # Convert to double if needed
                        if isinstance(val.type, ir.IntType):
                            val = self.builder.sitofp(val, double)
                        elif isinstance(val.type, ir.PointerType):
                            # pyobj — convert through bridge
                            val = self._convert_pyobj_to_numeric(val, arg_node)
                            if val is None:
                                return None
                        args.append(val)
                    result = self.builder.call(self.runtime[rt_key], args)
                    # floor() and ceil() return int in Python (not float)
                    if func_name in ("floor", "ceil"):
                        return self.builder.fptosi(result, i64)
                    return result
                # Special case: math.log(x, base) — 2-arg log
                if func_name == "log" and len(node.args) == 2:
                    x = self._emit_expr_value(node.args[0])
                    base = self._emit_expr_value(node.args[1])
                    if isinstance(x.type, ir.IntType):
                        x = self.builder.sitofp(x, double)
                    if isinstance(base.type, ir.IntType):
                        base = self.builder.sitofp(base, double)
                    log_x = self.builder.call(self.runtime["math_log"], [x])
                    log_base = self.builder.call(self.runtime["math_log"], [base])
                    return self.builder.fdiv(log_x, log_base)
        return None

    def _emit_native_module_attr(self, mod_name: str, attr_name: str) -> ir.Value | None:
        """Emit a native module attribute access (e.g. math.pi).
        Returns the constant value, or None if not natively supported."""
        if attr_name in self._MATH_CONSTANTS:
            return ir.Constant(double, self._MATH_CONSTANTS[attr_name])
        return None

    def _emit_builtin_filter(self, node: ast.Call) -> ir.Value:
        """Emit filter(func, iterable) as an inline loop.

        For each element, calls the predicate and appends to the result
        list only if the predicate returns truthy. Handles all element
        types (int, str, etc.) by passing the raw data to the predicate.
        """
        fn_node = node.args[0]
        seq = self._emit_expr_value(node.args[1])
        fn_ptr = self._get_unary_func_ptr(fn_node, node)
        result = self.builder.call(self.runtime["list_new"], [])
        length = self.builder.call(self.runtime["list_length"], [seq])

        idx_alloca = self._create_entry_alloca(i64, "filt.idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = self._new_block("filt.cond")
        body_block = self._new_block("filt.body")
        end_block = self._new_block("filt.end")

        self.builder.branch(cond_block)
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, length)
        self.builder.cbranch(cond, body_block, end_block)

        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)
        # Get element as FpyValue (preserves tag)
        elem_tag_a = self._create_entry_alloca(i32, "filt.etag")
        elem_data_a = self._create_entry_alloca(i64, "filt.edata")
        self.builder.call(self.runtime["list_get_fv"],
                          [seq, idx, elem_tag_a, elem_data_a])
        elem_data = self.builder.load(elem_data_a)
        elem_tag = self.builder.load(elem_tag_a)

        # Call predicate via call_ptr1 (handles closures via magic number)
        pred_result = self.builder.call(
            self.runtime["call_ptr1"], [fn_ptr, elem_data])
        # Check truthiness — non-zero means keep
        is_truthy = self.builder.icmp_signed(
            "!=", pred_result, ir.Constant(i64, 0))

        keep_block = self._new_block("filt.keep")
        skip_block = self._new_block("filt.skip")
        self.builder.cbranch(is_truthy, keep_block, skip_block)

        self.builder.position_at_end(keep_block)
        # Append with original tag preserved
        self.builder.call(self.runtime["list_append_fv"],
                          [result, elem_tag, elem_data])
        self.builder.branch(skip_block)

        self.builder.position_at_end(skip_block)
        next_idx = self.builder.add(
            self.builder.load(idx_alloca), ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        self.builder.position_at_end(end_block)
        return result

    def _emit_builtin_len(self, node: ast.Call) -> ir.Value:
        """Emit len() builtin."""
        if len(node.args) != 1:
            raise CodeGenError("len() takes exactly one argument", node)
        arg_node = node.args[0]
        if self._is_set_expr(arg_node):
            value = self._emit_expr_value(arg_node)
            if isinstance(value.type, ir.IntType):
                value = self.builder.inttoptr(value, i8_ptr)
            return self.builder.call(self.runtime["dict_length"], [value])
        if self._is_list_expr(arg_node) or self._is_tuple_expr(arg_node):
            value = self._emit_expr_value(arg_node)
            return self.builder.call(self.runtime["list_length"], [value])
        if self._is_dict_expr(arg_node):
            value = self._emit_expr_value(arg_node)
            return self.builder.call(self.runtime["dict_length"], [value])
        # __len__ on user-class objects
        if self._is_obj_expr(arg_node):
            obj_cls = self._infer_object_class(arg_node)
            if obj_cls and self._class_has_method(obj_cls, "__len__"):
                obj = self._emit_expr_value(arg_node)
                if isinstance(obj.type, ir.IntType):
                    obj = self.builder.inttoptr(obj, i8_ptr)
                name_ptr = self._make_string_constant("__len__")
                return self.builder.call(
                    self.runtime["obj_call_method0"], [obj, name_ptr])
        # pyobj-tagged variable (from CPython bridge): call len() directly
        if (isinstance(arg_node, ast.Name)
                and arg_node.id in self.variables
                and self.variables[arg_node.id][1] == "pyobj"):
            obj = self._load_variable(arg_node.id, arg_node)
            if isinstance(obj.type, ir.IntType):
                obj = self.builder.inttoptr(obj, i8_ptr)
            return self.builder.call(self.runtime["cpython_len"], [obj])
        # CPython method call expression: len(module.func(...))
        if (isinstance(arg_node, ast.Call)
                and isinstance(arg_node.func, ast.Attribute)
                and isinstance(arg_node.func.value, ast.Name)
                and arg_node.func.value.id in self.variables
                and self.variables[arg_node.func.value.id][1] == "pyobj"):
            obj = self._emit_cpython_call_raw(arg_node)
            return self.builder.call(self.runtime["cpython_len"], [obj])
        arg = self._emit_expr_value(arg_node)
        if isinstance(arg.type, ir.PointerType):
            return self.builder.call(self.runtime["str_len"], [arg])
        raise CodeGenError("len() on unsupported type", node)

    def _emit_builtin_sorted(self, node: ast.Call) -> ir.Value:
        """Emit sorted() — returns a new sorted list. Supports reverse=/key= keywords."""
        if len(node.args) != 1:
            raise CodeGenError("sorted() takes exactly one argument", node)
        reverse = False
        key_func = None
        for kw in node.keywords:
            if kw.arg == "reverse":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
                    reverse = kw.value.value
                else:
                    raise CodeGenError("sorted(reverse=) must be a literal True/False", node)
            elif kw.arg == "key":
                key_func = kw.value

        if key_func is not None:
            arg = self._emit_expr_value(node.args[0])
            fn_ptr = self._get_unary_func_ptr(key_func, node)
            # Determine if key function returns strings (e.g. lambda x: x[0]
            # on a list of strings). Use string comparison sort in that case.
            key_returns_str = False
            if isinstance(key_func, ast.Lambda):
                body = key_func.body
                if isinstance(body, ast.Subscript):
                    # key=lambda x: x[i] on strings → returns string
                    elem_type = self._get_list_elem_type(node.args[0])
                    if elem_type == "str":
                        key_returns_str = True
                elif isinstance(body, ast.Name):
                    # key=lambda x: x on strings → returns string
                    elem_type = self._get_list_elem_type(node.args[0])
                    if elem_type == "str":
                        key_returns_str = True
            elif isinstance(key_func, ast.Name):
                if key_func.id == "str":
                    key_returns_str = True
                elif key_func.id in self._user_functions:
                    info = self._user_functions[key_func.id]
                    if info.ret_tag == "str":
                        key_returns_str = True
            sort_fn = "list_sorted_by_key_str" if key_returns_str else "list_sorted_by_key_int"
            result = self.builder.call(self.runtime[sort_fn], [arg, fn_ptr])
            if reverse:
                result = self.builder.call(self.runtime["list_reversed"], [result])
            return result

        # If sorting a set, convert to list first (extract keys from dict)
        if self._is_set_expr(node.args[0]):
            arg = self._emit_expr_value(node.args[0])
            if isinstance(arg.type, ir.IntType):
                arg = self.builder.inttoptr(arg, i8_ptr)
            keys = self.builder.call(self.runtime["set_to_list"], [arg])
            result = self.builder.call(self.runtime["list_sorted"], [keys])
        # If sorting a dict, sort its keys
        elif self._is_dict_expr(node.args[0]):
            arg = self._emit_expr_value(node.args[0])
            keys = self.builder.call(self.runtime["dict_keys"], [arg])
            result = self.builder.call(self.runtime["list_sorted"], [keys])
        else:
            arg = self._emit_expr_value(node.args[0])
            result = self.builder.call(self.runtime["list_sorted"], [arg])
        if reverse:
            result = self.builder.call(self.runtime["list_reversed"], [result])
        return result

    def _get_unary_func_ptr(self, fn_node: ast.expr, node: ast.AST) -> ir.Value:
        """Get a function pointer to a unary int64(int64) function.

        Accepts a lambda expression or a function name (that's already declared).
        Returns an i8* pointer (cast from function pointer).
        """
        if isinstance(fn_node, ast.Name):
            if fn_node.id in self._user_functions:
                info = self._user_functions[fn_node.id]
                # If the function uses FV ABI, generate/return an int(int) shim
                # that wraps and unwraps FpyValue.
                if info.uses_fv_abi:
                    shim = self._get_or_emit_int_int_shim(info)
                    return self.builder.bitcast(shim, i8_ptr)
                return self.builder.bitcast(info.func, i8_ptr)
            # Builtin functions used as function pointers (e.g. key=len,
            # map(str, ...)). Emit small i64(i64) shim functions that call
            # the appropriate runtime function with the correct types.
            if fn_node.id in ("str", "int", "abs", "len"):
                return self._get_or_emit_builtin_shim(fn_node.id)
            # Variable holding a closure/function
            if fn_node.id in self.variables:
                val = self._load_variable(fn_node.id, node)
                if isinstance(val.type, ir.IntType):
                    val = self.builder.inttoptr(val, i8_ptr)
                return val
        if isinstance(fn_node, ast.Lambda):
            # Emit an inline lambda as a standalone i64(i64) function
            if len(fn_node.args.args) != 1:
                raise CodeGenError("Inline lambda must take exactly one argument", node)
            fn = self._emit_inline_unary_lambda(fn_node, node)
            return self.builder.bitcast(fn, i8_ptr)
        raise CodeGenError("key/map/filter function must be a named function or lambda", node)

    def _get_or_emit_builtin_shim(self, name: str) -> ir.Value:
        """Get or emit an i64(i64) shim for a builtin function used as a
        function pointer (e.g. key=len, map(str, ...)).

        Each shim is emitted once and cached. The shim calls the appropriate
        runtime function with the correct argument types.
        """
        if not hasattr(self, '_builtin_shims'):
            self._builtin_shims = {}
        if name in self._builtin_shims:
            return self.builder.bitcast(self._builtin_shims[name], i8_ptr)

        saved = (self.function, self.builder)
        shim_ft = ir.FunctionType(i64, [i64])
        shim = ir.Function(self.module, shim_ft,
                           name=f"fastpy.builtin_shim.{name}")
        shim.linkage = "private"
        entry = shim.append_basic_block("entry")
        b = ir.IRBuilder(entry)
        arg = shim.args[0]

        if name == "abs":
            neg = b.neg(arg)
            is_neg = b.icmp_signed("<", arg, ir.Constant(i64, 0))
            result = b.select(is_neg, neg, arg)
            b.ret(result)
        elif name == "len":
            # arg is a pointer (string or list) passed as i64
            ptr = b.inttoptr(arg, i8_ptr)
            result = b.call(self.runtime["str_len"], [ptr])
            b.ret(result)
        elif name == "str":
            result = b.call(self.runtime["int_to_str"], [arg])
            b.ret(b.ptrtoint(result, i64))
        elif name == "int":
            b.ret(arg)  # identity for int-typed elements
        else:
            b.ret(arg)

        self.function, self.builder = saved
        self._builtin_shims[name] = shim
        return self.builder.bitcast(shim, i8_ptr)

    def _get_or_emit_int_int_shim(self, info: "FuncInfo") -> ir.Function:
        """Get or emit a bare int64(int64) shim for an FV-ABI user function.

        The shim wraps the int arg as FpyValue(INT), calls the FV function,
        and extracts the int from the returned FpyValue. Used where we need
        a raw function pointer with int(int) ABI (sorted(key=), map, filter).
        """
        if not hasattr(self, '_int_int_shims'):
            self._int_int_shims = {}
        func_name = info.func.name
        if func_name in self._int_int_shims:
            return self._int_int_shims[func_name]

        # Save state
        saved = (self.function, self.builder)

        shim_name = f"{func_name}.int_shim"
        shim_type = ir.FunctionType(i64, [i64])
        shim = ir.Function(self.module, shim_type, name=shim_name)
        self.function = shim
        entry = shim.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)

        # Wrap arg as FpyValue(INT), call, extract int from return
        arg_fv = self._fv_from_int(shim.args[0])
        ret_fv = self.builder.call(info.func, [arg_fv])
        self.builder.ret(self._fv_as_int(ret_fv))

        self.function, self.builder = saved
        self._int_int_shims[func_name] = shim
        return shim

    def _emit_inline_unary_lambda(self, lam: ast.Lambda, node: ast.AST) -> ir.Function:
        """Emit a lambda `lambda x: <expr>` as an LLVM i64(i64) function."""
        # Generate a unique name for the lambda
        lam_name = f"fastpy.inline_lambda.{self._block_counter}"
        self._block_counter += 1
        param_name = lam.args.args[0].arg
        func_type = ir.FunctionType(i64, [i64])
        func = ir.Function(self.module, func_type, name=lam_name)
        func.args[0].name = param_name

        # Infer the lambda parameter type from context. For sorted/map/filter,
        # the param type matches the list's element type.
        param_tag = "int"
        if isinstance(node, ast.Call) and len(node.args) >= 1:
            # Find the list argument (not the function argument).
            # sorted(list, key=lambda) → args[0] is the list
            # map(lambda, list) → args[1] is the list
            # filter(lambda, list) → args[1] is the list
            list_node = None
            for arg in node.args:
                if not isinstance(arg, ast.Lambda):
                    list_node = arg
                    break
            if list_node is None and len(node.args) >= 2:
                list_node = node.args[-1]
            if list_node is not None:
                elem_type = self._get_list_elem_type(list_node)
                if elem_type == "str":
                    param_tag = "str"
                elif elem_type in ("list", "tuple"):
                    param_tag = "list"

        # Save current emission state
        saved = (self.function, self.builder, self.variables, self._loop_stack,
                 self._finally_stack, self._list_append_types, self._current_scope_stmts)
        self.function = func
        entry = func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        self.variables = {}
        self._loop_stack = []
        self._finally_stack = []
        self._list_append_types = {}
        self._current_scope_stmts = []

        # Param — type determines how it's stored and accessed
        if param_tag == "str":
            ptr = self.builder.inttoptr(func.args[0], i8_ptr)
            alloca = self.builder.alloca(i8_ptr, name=param_name)
            self.builder.store(ptr, alloca)
            self.variables[param_name] = (alloca, "str")
        elif param_tag == "list":
            ptr = self.builder.inttoptr(func.args[0], i8_ptr)
            alloca = self.builder.alloca(i8_ptr, name=param_name)
            self.builder.store(ptr, alloca)
            self.variables[param_name] = (alloca, "list:int")
        else:
            alloca = self.builder.alloca(i64, name=param_name)
            self.builder.store(func.args[0], alloca)
            self.variables[param_name] = (alloca, "int")

        # Emit the body expression and return it
        result = self._emit_expr_value(lam.body)
        if isinstance(result.type, ir.IntType) and result.type.width < 64:
            result = self.builder.zext(result, i64)
        elif isinstance(result.type, ir.DoubleType):
            result = self.builder.fptosi(result, i64)
        elif isinstance(result.type, ir.PointerType):
            result = self.builder.ptrtoint(result, i64)
        self.builder.ret(result)

        # Restore
        (self.function, self.builder, self.variables, self._loop_stack,
         self._finally_stack, self._list_append_types, self._current_scope_stmts) = saved
        return func

    def _emit_builtin_isinstance(self, node: ast.Call) -> ir.Value:
        """Emit isinstance(obj, ClassName) or isinstance(obj, builtin_type)."""
        if len(node.args) != 2:
            raise CodeGenError("isinstance() takes exactly 2 arguments", node)
        class_node = node.args[1]
        # isinstance(x, (Type1, Type2, ...)) — tuple of types
        if isinstance(class_node, ast.Tuple):
            type_names = []
            for elt in class_node.elts:
                if isinstance(elt, ast.Name):
                    type_names.append(elt.id)
                else:
                    raise CodeGenError("isinstance() tuple must contain type names", node)
            # Check each type; return True if any matches
            for tname in type_names:
                # Build a temporary isinstance call for each type
                temp = ast.Call(
                    func=node.func,
                    args=[node.args[0], ast.Name(id=tname, ctx=ast.Load())],
                    keywords=[])
                ast.copy_location(temp, node)
                ast.copy_location(temp.args[1], node)
            # Use OR logic: emit isinstance for each type and combine
            arg = node.args[0]
            actual = self._static_type_of(arg)
            builtin_types = ("int", "str", "float", "list", "dict", "bool", "tuple")
            # Fast path: all builtin types
            if all(t in builtin_types for t in type_names):
                for tname in type_names:
                    if tname == "int" and actual in ("int", "bool"):
                        return ir.Constant(i32, 1)
                    if tname == actual:
                        return ir.Constant(i32, 1)
                return ir.Constant(i32, 0)
            # Mixed or user-class types: runtime check
            result = None
            for tname in type_names:
                if tname in builtin_types:
                    if (tname == "int" and actual in ("int", "bool")) or tname == actual:
                        return ir.Constant(i32, 1)
                    continue
                if tname in self._user_classes:
                    obj = self._emit_expr_value(node.args[0])
                    if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
                        obj = self.builder.inttoptr(obj, i8_ptr)
                    cls_info = self._user_classes[tname]
                    class_id = self.builder.load(cls_info.class_id_global)
                    r = self.builder.call(self.runtime["isinstance"], [obj, class_id])
                    result = self.builder.or_(result, r) if result is not None else r
            return result if result is not None else ir.Constant(i32, 0)
        if not isinstance(class_node, ast.Name):
            raise CodeGenError("isinstance() second arg must be a class name", node)
        class_name = class_node.id

        # Handle built-in types by checking the AST-level type of the first argument.
        # This gives a compile-time constant answer since all variables have a known type tag.
        if class_name in ("int", "str", "float", "list", "dict", "bool", "tuple"):
            arg = node.args[0]
            actual = self._static_type_of(arg)
            # Python: isinstance(True, int) is True; we follow that.
            if class_name == "int" and actual in ("int", "bool"):
                return ir.Constant(i32, 1)
            if class_name == actual:
                return ir.Constant(i32, 1)
            return ir.Constant(i32, 0)

        obj = self._emit_expr_value(node.args[0])
        if class_name not in self._user_classes:
            raise CodeGenError(f"isinstance(): unknown class '{class_name}'", node)
        # Coerce obj to i8* if needed (may come in as i64 from FV unwrap).
        if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
            obj = self.builder.inttoptr(obj, i8_ptr)
        # For monomorphized classes, check against all variants: obj is an
        # instance of the original class if it matches any variant's class_id.
        if class_name in self._monomorphized_classes:
            sigs = self._monomorphized_classes[class_name]
            if not sigs:
                return ir.Constant(i32, 0)
            result: ir.Value | None = None
            for sig in sigs:
                variant = f"{class_name}__{self._mangle_sig(sig)}"
                v_info = self._user_classes.get(variant)
                if v_info is None:
                    continue
                class_id = self.builder.load(v_info.class_id_global)
                r = self.builder.call(
                    self.runtime["isinstance"], [obj, class_id])
                if result is None:
                    result = r
                else:
                    result = self.builder.or_(result, r)
            return result if result is not None else ir.Constant(i32, 0)
        cls_info = self._user_classes[class_name]
        class_id = self.builder.load(cls_info.class_id_global)
        result = self.builder.call(self.runtime["isinstance"], [obj, class_id])
        # result is i32 (0 or 1), use it as our bool type
        return result

    def _static_type_of(self, node: ast.expr) -> str:
        """Best-effort static type determination for isinstance()."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, str):
                return "str"
        if isinstance(node, (ast.List, ast.ListComp)):
            return "list"
        if isinstance(node, (ast.Dict, ast.DictComp)):
            return "dict"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.JoinedStr):
            return "str"
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, tag = self.variables[node.id]
            if tag.startswith("list"):
                return "list"
            if tag in ("int", "float", "str", "dict", "bool"):
                return tag
        return "unknown"

    def _emit_method_call(self, node: ast.Call) -> ir.Value:
        """Emit a method call like s.lower(), lst.append(), ClassName.static()."""
        attr = node.func
        method = attr.attr

        # Check for super().method(args) — transform to ParentClass.method(self, args)
        if (isinstance(attr.value, ast.Call)
                and isinstance(attr.value.func, ast.Name)
                and attr.value.func.id == "super"):
            if self._current_class is None:
                raise CodeGenError("super() can only be used inside a class method", node)
            cls_info = self._user_classes.get(self._current_class)
            if cls_info is None or cls_info.parent_name is None:
                raise CodeGenError(f"Class {self._current_class} has no parent class", node)
            parent_info = self._user_classes.get(cls_info.parent_name)
            if parent_info is None or method not in parent_info.methods:
                raise CodeGenError(
                    f"Parent class {cls_info.parent_name} has no method {method}", node)
            func = parent_info.methods[method]
            # Pass current self as first arg, then the user args
            self_val = self._load_variable("self", node)
            args = [self_val] + [self._emit_expr_value(a) for a in node.args]
            coerced = []
            for val, param in zip(args, func.args):
                if val.type != param.type:
                    if isinstance(param.type, ir.IntType) and isinstance(val.type, ir.PointerType):
                        val = self.builder.ptrtoint(val, param.type)
                    elif isinstance(param.type, ir.PointerType) and isinstance(val.type, ir.IntType):
                        val = self.builder.inttoptr(val, param.type)
                coerced.append(val)
            return self.builder.call(func, coerced)

        # Check for static/classmethod call on a class: ClassName.method(args)
        if isinstance(attr.value, ast.Name) and attr.value.id in self._user_classes:
            cls_info = self._user_classes[attr.value.id]
            if method in cls_info.methods:
                func = cls_info.methods[method]
                is_classmethod = method in (cls_info.classmethods or set())
                args = []
                if is_classmethod:
                    # Prepend class_id (loaded from the class's global) as the cls arg
                    class_id = self.builder.load(cls_info.class_id_global)
                    args.append(class_id)
                args.extend(self._emit_expr_value(a) for a in node.args)
                # Coerce args
                coerced = []
                for val, param in zip(args, func.args):
                    if val.type != param.type:
                        if (isinstance(param.type, ir.IntType) and isinstance(val.type, ir.IntType)
                                and param.type.width != val.type.width):
                            if param.type.width > val.type.width:
                                val = self.builder.zext(val, param.type)
                            else:
                                val = self.builder.trunc(val, param.type)
                        elif isinstance(param.type, ir.IntType) and isinstance(val.type, ir.PointerType):
                            val = self.builder.ptrtoint(val, param.type)
                        elif isinstance(param.type, ir.PointerType) and isinstance(val.type, ir.IntType):
                            val = self.builder.inttoptr(val, param.type)
                        elif isinstance(param.type, ir.IntType) and isinstance(val.type, ir.DoubleType):
                            val = self.builder.bitcast(val, param.type)
                        elif isinstance(param.type, ir.DoubleType) and isinstance(val.type, ir.IntType):
                            val = self.builder.bitcast(val, param.type)
                    coerced.append(val)
                return self.builder.call(func, coerced)

        # Check if object is a list
        if self._is_list_expr(attr.value):
            obj = self._emit_expr_value(attr.value)
            if method == "append" and len(node.args) == 1:
                self._emit_list_append_expr(obj, node.args[0])
                return obj
            if method == "pop" and len(node.args) == 0:
                return self.builder.call(self.runtime["list_pop_int"], [obj])
            if method == "index" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                return self.builder.call(self.runtime["list_index"], [obj, val])
            if method == "count" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                return self.builder.call(self.runtime["list_count"], [obj, val])
            if method == "extend" and len(node.args) == 1:
                other = self._emit_expr_value(node.args[0])
                self.builder.call(self.runtime["list_extend"], [obj, other])
                return obj
            if method == "sort" and len(node.args) == 0:
                self.builder.call(self.runtime["list_sort"], [obj])
                # Handle reverse=True keyword
                for kw in node.keywords:
                    if kw.arg == "reverse":
                        if (isinstance(kw.value, ast.Constant)
                                and kw.value.value is True):
                            self.builder.call(
                                self.runtime["list_reverse_inplace"], [obj])
                return obj
            if method == "reverse" and len(node.args) == 0:
                self.builder.call(self.runtime["list_reverse_inplace"], [obj])
                return obj
            if method == "remove" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                if isinstance(val.type, ir.PointerType):
                    self.builder.call(self.runtime["list_remove_str"], [obj, val])
                else:
                    self.builder.call(self.runtime["list_remove"], [obj, val])
                return obj
            if method == "insert" and len(node.args) == 2:
                idx = self._emit_expr_value(node.args[0])
                val = self._emit_expr_value(node.args[1])
                if isinstance(val.type, ir.PointerType):
                    self.builder.call(self.runtime["list_insert_str"], [obj, idx, val])
                else:
                    self.builder.call(self.runtime["list_insert_int"], [obj, idx, val])
                return obj
            if method == "copy" and len(node.args) == 0:
                return self.builder.call(self.runtime["list_copy"], [obj])
            if method == "clear" and len(node.args) == 0:
                self.builder.call(self.runtime["list_clear"], [obj])
                return obj
            if method == "discard" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                if isinstance(val.type, ir.PointerType):
                    val = self.builder.ptrtoint(val, i64)
                self.builder.call(self.runtime["set_discard"], [obj, val])
                return obj
            raise CodeGenError(f"Unsupported list method: .{method}()", node)

        # Check if object is a set (dict-backed)
        if self._is_set_expr(attr.value):
            obj = self._emit_expr_value(attr.value)
            if isinstance(obj.type, ir.IntType):
                obj = self.builder.inttoptr(obj, i8_ptr)
            if method == "add" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                tag, data = self._bare_to_tag_data(val, node.args[0])
                self.builder.call(self.runtime["set_add_fv"],
                                  [obj, ir.Constant(i32, tag), data])
                return obj
            if method == "discard" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                tag, data = self._bare_to_tag_data(val, node.args[0])
                self.builder.call(self.runtime["set_discard_fv"],
                                  [obj, ir.Constant(i32, tag), data])
                return obj
            if method == "remove" and len(node.args) == 1:
                val = self._emit_expr_value(node.args[0])
                tag, data = self._bare_to_tag_data(val, node.args[0])
                self.builder.call(self.runtime["set_discard_fv"],
                                  [obj, ir.Constant(i32, tag), data])
                return obj
            raise CodeGenError(f"Unsupported set method: .{method}()", node)

        # Check if object is a dict
        if self._is_dict_expr(attr.value):
            obj = self._emit_expr_value(attr.value)
            if method == "keys":
                return self.builder.call(self.runtime["dict_keys"], [obj])
            if method == "values":
                return self.builder.call(self.runtime["dict_values"], [obj])
            if method == "items":
                return self.builder.call(self.runtime["dict_items"], [obj])
            if method == "get":
                if len(node.args) >= 1:
                    key = self._emit_expr_value(node.args[0])
                    if len(node.args) >= 2:
                        default = self._emit_expr_value(node.args[1])
                        # Convert non-pointer default to string representation
                        if not isinstance(default.type, ir.PointerType):
                            default = self.builder.call(self.runtime["int_to_str"], [default])
                    else:
                        default = self._make_string_constant("None")
                    return self.builder.call(self.runtime["dict_get_default"], [obj, key, default])
            if method == "update":
                if len(node.args) == 1:
                    other = self._emit_expr_value(node.args[0])
                    self.builder.call(self.runtime["dict_update"], [obj, other])
                    return obj
            if method == "pop":
                if len(node.args) == 1:
                    key = self._emit_expr_value(node.args[0])
                    # Heuristic: use int pop if we can't tell; returning str by default
                    return self.builder.call(self.runtime["dict_pop_int"], [obj, key])
            if method == "setdefault":
                if len(node.args) == 2:
                    key = self._emit_expr_value(node.args[0])
                    default = self._emit_expr_value(node.args[1])
                    if isinstance(default.type, ir.PointerType):
                        self.builder.call(self.runtime["dict_setdefault_list"], [obj, key, default])
                    else:
                        self.builder.call(self.runtime["dict_setdefault_int"], [obj, key, default])
                    return obj
            raise CodeGenError(f"Unsupported dict method: .{method}()", node)

        # Check if object is a known user-class instance
        if self._is_obj_expr(attr.value):
            obj = self._emit_expr_value(attr.value)
            if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
                obj = self.builder.inttoptr(obj, i8_ptr, name="obj.ptr")
            method_name_ptr = self._make_string_constant(method)
            n_args = len(node.args)
            # Check which params are mixed for this method
            obj_cls = self._infer_object_class(attr.value)
            method_mixed = set()
            if obj_cls:
                mkey = f"{obj_cls}.{method}"
                method_mixed = getattr(self, '_mixed_param_methods', {}).get(mkey, set())
            # Resolve keyword arguments → positional by consulting method AST
            resolved_arg_nodes = list(node.args)
            if node.keywords and obj_cls:
                # Find the method's AST to get param names and defaults
                m_ast = None
                cn = obj_cls
                while cn and cn in self._user_classes:
                    ci = self._user_classes[cn]
                    if ci.method_asts and method in ci.method_asts:
                        m_ast = ci.method_asts[method]
                        break
                    cn = ci.parent_name
                if m_ast is not None:
                    m_params = [a.arg for a in m_ast.args.args[1:]]  # skip self
                    m_defaults = m_ast.args.defaults
                    kw_nodes: dict[int, ast.expr] = {}
                    for kw in node.keywords:
                        if kw.arg is None:
                            continue
                        if kw.arg not in m_params:
                            raise CodeGenError(
                                f".{method}() got unexpected keyword '{kw.arg}'",
                                node,
                            )
                        idx = m_params.index(kw.arg)
                        if idx < len(resolved_arg_nodes):
                            raise CodeGenError(
                                f".{method}() got multiple values for '{kw.arg}'",
                                node,
                            )
                        kw_nodes[idx] = kw.value
                    while len(resolved_arg_nodes) < len(m_params):
                        idx = len(resolved_arg_nodes)
                        if idx in kw_nodes:
                            resolved_arg_nodes.append(kw_nodes[idx])
                        else:
                            default_idx = idx - (len(m_params) - len(m_defaults))
                            if default_idx >= 0 and default_idx < len(m_defaults):
                                resolved_arg_nodes.append(m_defaults[default_idx])
                            else:
                                raise CodeGenError(
                                    f".{method}() missing argument at position {idx}",
                                    node,
                                )
            # For non-kwarg calls, also fill in defaults for missing positional args
            elif obj_cls and not node.keywords:
                m_ast = None
                cn = obj_cls
                while cn and cn in self._user_classes:
                    ci = self._user_classes[cn]
                    if ci.method_asts and method in ci.method_asts:
                        m_ast = ci.method_asts[method]
                        break
                    cn = ci.parent_name
                if m_ast is not None:
                    m_params = [a.arg for a in m_ast.args.args[1:]]
                    m_defaults = m_ast.args.defaults
                    while len(resolved_arg_nodes) < len(m_params):
                        idx = len(resolved_arg_nodes)
                        default_idx = idx - (len(m_params) - len(m_defaults))
                        if default_idx >= 0 and default_idx < len(m_defaults):
                            resolved_arg_nodes.append(m_defaults[default_idx])
                        else:
                            break
            n_args = len(resolved_arg_nodes)

            # Evaluate and coerce args to i64 (runtime dispatch expects i64).
            # For "mixed" params, pass (tag_i64, data_i64) as two separate args.
            call_args = []
            for arg_idx, arg_node in enumerate(resolved_arg_nodes):
                param_idx = arg_idx + 1  # +1 for self
                v = self._emit_expr_value(arg_node)
                if param_idx in method_mixed:
                    # Mixed param: pass tag and data as two separate i64 args
                    tag_int, data_val = self._bare_to_tag_data(v, value_node=arg_node)
                    call_args.append(ir.Constant(i64, tag_int))
                    call_args.append(data_val)
                else:
                    if isinstance(v.type, ir.PointerType):
                        v = self.builder.ptrtoint(v, i64)
                    elif isinstance(v.type, ir.DoubleType):
                        v = self.builder.bitcast(v, i64)
                    elif isinstance(v.type, ir.IntType) and v.type.width != 64:
                        v = self.builder.zext(v, i64)
                    call_args.append(v)

            # Determine if method returns double
            method_ret_type = self._find_method_return_type(attr.value, method)
            is_double_ret = method_ret_type and isinstance(method_ret_type, ir.DoubleType)

            # Direct dispatch optimization: when the object's class is known
            # statically and there are no mixed params, call the method
            # function directly instead of going through obj_call_methodN.
            # This skips string comparison and enables LLVM inlining.
            if obj_cls and not method_mixed:
                # Walk class chain to find the actual method (handles inheritance)
                direct_func = None
                cn = obj_cls
                while cn and cn in self._user_classes:
                    ci = self._user_classes[cn]
                    if method in ci.methods:
                        direct_func = ci.methods[method]
                        break
                    cn = ci.parent_name
                # Virtual dispatch: if the receiver's concrete class isn't
                # pinned (e.g., `self` inside a class method — could be any
                # subclass) and some subclass of obj_cls overrides this
                # method, we can't statically bind.
                if (direct_func is not None
                        and self._method_overridden_in_subclass(obj_cls, method)
                        and self._receiver_may_be_subclass(attr.value)):
                    direct_func = None
                if direct_func is not None:
                    # Coerce args to match the method's LLVM signature
                    direct_args = [obj]  # self
                    for i, val in enumerate(call_args):
                        if 1 + i >= len(direct_func.args):
                            break
                        expected = direct_func.args[1 + i].type
                        if val.type != expected:
                            if (isinstance(expected, ir.IntType)
                                    and isinstance(val.type, ir.IntType)
                                    and expected.width != val.type.width):
                                if expected.width > val.type.width:
                                    val = self.builder.zext(val, expected)
                                else:
                                    val = self.builder.trunc(val, expected)
                            elif (isinstance(expected, ir.IntType)
                                    and isinstance(val.type, ir.PointerType)):
                                val = self.builder.ptrtoint(val, expected)
                            elif (isinstance(expected, ir.PointerType)
                                    and isinstance(val.type, ir.IntType)):
                                val = self.builder.inttoptr(val, expected)
                            elif (isinstance(expected, ir.DoubleType)
                                    and isinstance(val.type, ir.IntType)):
                                val = self.builder.bitcast(val, expected)
                            elif (isinstance(expected, ir.IntType)
                                    and isinstance(val.type, ir.DoubleType)):
                                val = self.builder.bitcast(val, expected)
                        direct_args.append(val)
                    # Call the method function directly
                    result = self.builder.call(direct_func, direct_args)
                    # Post-process result based on actual return type
                    ret_type = direct_func.return_value.type
                    if isinstance(ret_type, ir.VoidType):
                        return ir.Constant(i64, 0)  # void methods — return placeholder
                    # Cast the return to the form the caller expects
                    # (runtime dispatch returns i64, but direct returns native type)
                    # Keep as-is; downstream code expects the native type.
                    return result

            # Use actual dispatch arg count (mixed params expand to 2 args each)
            n_dispatch_args = len(call_args)
            if n_dispatch_args == 0:
                if is_double_ret:
                    result = self.builder.call(
                        self.runtime["obj_call_method0_double"], [obj, method_name_ptr])
                else:
                    result = self.builder.call(
                        self.runtime["obj_call_method0"], [obj, method_name_ptr])
            elif n_dispatch_args == 1:
                if is_double_ret:
                    result = self.builder.call(
                        self.runtime["obj_call_method1_double"], [obj, method_name_ptr, call_args[0]])
                else:
                    result = self.builder.call(
                        self.runtime["obj_call_method1"], [obj, method_name_ptr, call_args[0]])
            elif n_dispatch_args == 2:
                result = self.builder.call(
                    self.runtime["obj_call_method2"], [obj, method_name_ptr, call_args[0], call_args[1]])
            elif n_dispatch_args == 3:
                result = self.builder.call(
                    self.runtime["obj_call_method3"],
                    [obj, method_name_ptr, call_args[0], call_args[1], call_args[2]])
            elif n_dispatch_args == 4:
                result = self.builder.call(
                    self.runtime["obj_call_method4"],
                    [obj, method_name_ptr, call_args[0], call_args[1], call_args[2], call_args[3]])
            else:
                raise CodeGenError(f"Method call with {n_dispatch_args} dispatch args not supported (max 4)", node)

            # Check if the method returns a string or bool — cast from i64
            if not is_double_ret:
                ret_type = self._find_method_return_type(attr.value, method)
                if ret_type and isinstance(ret_type, ir.PointerType):
                    result = self.builder.inttoptr(result, i8_ptr)
                elif ret_type and isinstance(ret_type, ir.IntType) and ret_type.width == 32:
                    result = self.builder.trunc(result, i32)
            return result

        obj = self._emit_expr_value(attr.value)

        if isinstance(obj.type, ir.PointerType):
            # String methods
            if method == "lower":
                return self.builder.call(self.runtime["str_lower"], [obj])
            if method == "upper":
                return self.builder.call(self.runtime["str_upper"], [obj])
            if method == "strip":
                if len(node.args) == 1:
                    chars = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_strip_chars"], [obj, chars])
                return self.builder.call(self.runtime["str_strip"], [obj])
            if method == "lstrip":
                return self.builder.call(self.runtime["str_lstrip"], [obj])
            if method == "rstrip":
                return self.builder.call(self.runtime["str_rstrip"], [obj])
            if method == "isdigit":
                return self.builder.call(self.runtime["str_isdigit"], [obj])
            if method == "isalpha":
                return self.builder.call(self.runtime["str_isalpha"], [obj])
            if method == "isalnum":
                return self.builder.call(self.runtime["str_isalnum"], [obj])
            if method == "isspace":
                return self.builder.call(self.runtime["str_isspace"], [obj])
            if method == "capitalize":
                return self.builder.call(self.runtime["str_capitalize"], [obj])
            if method == "title":
                return self.builder.call(self.runtime["str_title"], [obj])
            if method == "swapcase":
                return self.builder.call(self.runtime["str_swapcase"], [obj])
            if method == "center":
                if len(node.args) == 1:
                    w = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_center"], [obj, w])
            if method == "ljust":
                if len(node.args) == 1:
                    w = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_ljust"], [obj, w])
            if method == "rjust":
                if len(node.args) == 1:
                    w = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_rjust"], [obj, w])
            if method == "zfill":
                if len(node.args) == 1:
                    w = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_zfill"], [obj, w])
            if method == "splitlines":
                return self.builder.call(self.runtime["str_splitlines"], [obj])
            if method == "split":
                if len(node.args) == 2:
                    sep = self._emit_expr_value(node.args[0])
                    maxsplit = self._emit_expr_value(node.args[1])
                    return self.builder.call(self.runtime["str_split_max"], [obj, sep, maxsplit])
                if len(node.args) == 1:
                    sep = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_split_max"], [obj, sep, ir.Constant(i64, -1)])
                return self.builder.call(self.runtime["str_split"], [obj])
            if method == "join":
                if len(node.args) == 1:
                    lst = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_join"], [obj, lst])
            if method == "replace":
                if len(node.args) == 2:
                    old = self._emit_expr_value(node.args[0])
                    new = self._emit_expr_value(node.args[1])
                    return self.builder.call(self.runtime["str_replace"], [obj, old, new])
            if method == "startswith":
                if len(node.args) == 1:
                    prefix = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_startswith"], [obj, prefix])
            if method == "endswith":
                if len(node.args) == 1:
                    suffix = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_endswith"], [obj, suffix])
            if method == "find":
                if len(node.args) == 1:
                    sub = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_find"], [obj, sub])
            if method == "rfind":
                if len(node.args) == 1:
                    sub = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_rfind"], [obj, sub])
            if method == "count":
                if len(node.args) == 1:
                    sub = self._emit_expr_value(node.args[0])
                    return self.builder.call(self.runtime["str_count"], [obj, sub])
            if method == "format":
                return self._emit_str_format(node, obj)
        raise CodeGenError(f"Unsupported method: .{method}()", node)

    def _method_overridden_in_subclass(self, base_class: str,
                                         method_name: str) -> bool:
        """True if any direct or transitive subclass of `base_class`
        defines `method_name` (overriding the base). Used to decide
        whether `self.method()` inside a class method needs virtual
        dispatch (runtime lookup) or can stay as a direct call.
        """
        for cls_name, cls_info in self._user_classes.items():
            if cls_name == base_class:
                continue
            # Walk cls_name's ancestry — if base_class is an ancestor and
            # method_name is defined in cls_name itself, it's an override.
            cn = cls_info.parent_name
            is_descendant = False
            while cn:
                if cn == base_class:
                    is_descendant = True
                    break
                parent_info = self._user_classes.get(cn)
                cn = parent_info.parent_name if parent_info else None
            if is_descendant and method_name in cls_info.methods:
                return True
        return False

    def _receiver_may_be_subclass(self, node: ast.expr) -> bool:
        """True if the receiver's runtime class could be a subclass of its
        statically-known class (requires virtual dispatch). This is the case
        for:
          - `self` inside a method body (could be any subclass)
          - a parameter typed as obj but not pinned to a specific class
          - a function return typed as obj
        False for direct constructor calls and local variables assigned
        from direct constructors — those have pinned runtime classes.
        """
        if isinstance(node, ast.Name) and node.id == "self":
            return True
        if isinstance(node, ast.Name) and node.id in self.variables:
            # If the variable's exact class came from a direct constructor,
            # the runtime class is pinned.
            if node.id in self._obj_var_class:
                return False
            return True
        # Method call returning obj — class may be subclass
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in self._user_classes:
                # Direct constructor — exact runtime class known
                return False
            return True
        if isinstance(node, ast.Attribute):
            return True
        return False

    def _method_returns_list(self, obj_node: ast.expr, method_name: str) -> bool:
        """Check if a class method returns a list, by inspecting its AST."""
        obj_cls = self._infer_object_class(obj_node)
        if obj_cls is None:
            return False
        cls_info = self._user_classes.get(obj_cls)
        if cls_info is None or not cls_info.method_asts:
            return False
        method_ast = cls_info.method_asts.get(method_name)
        if method_ast is None:
            return False
        # Check container attrs (including inherited)
        list_attrs: set[str] = set()
        c = obj_cls
        while c and c in self._class_container_attrs:
            la, _ = self._class_container_attrs[c]
            list_attrs |= la
            c = self._user_classes[c].parent_name if c in self._user_classes else None
        for n in ast.walk(method_ast):
            if isinstance(n, ast.Return) and n.value is not None:
                if isinstance(n.value, (ast.List, ast.ListComp)):
                    return True
                # return self.list_attr
                if (isinstance(n.value, ast.Attribute)
                        and isinstance(n.value.value, ast.Name)
                        and n.value.value.id == "self"
                        and n.value.attr in list_attrs):
                    return True
                # Return a var that was assigned a list
                if isinstance(n.value, ast.Name):
                    for s in ast.walk(method_ast):
                        if (isinstance(s, ast.Assign) and len(s.targets) == 1
                                and isinstance(s.targets[0], ast.Name)
                                and s.targets[0].id == n.value.id):
                            if isinstance(s.value, (ast.List, ast.ListComp)):
                                return True
                            # var = self.list_attr
                            if (isinstance(s.value, ast.Attribute)
                                    and isinstance(s.value.value, ast.Name)
                                    and s.value.value.id == "self"
                                    and s.value.attr in list_attrs):
                                return True
                # return list(self.dict.keys()) etc.
                if (isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Name)
                        and n.value.func.id == "list"):
                    return True
                # return self.list_attr[slice] — slice returns a list
                if (isinstance(n.value, ast.Subscript)
                        and isinstance(n.value.slice, ast.Slice)
                        and isinstance(n.value.value, ast.Attribute)
                        and isinstance(n.value.value.value, ast.Name)
                        and n.value.value.value.id == "self"
                        and n.value.value.attr in list_attrs):
                    return True
        return False

    def _method_returns_tuple(self, obj_node: ast.expr, method_name: str) -> bool:
        """Check if a class method returns a tuple, by inspecting its AST."""
        obj_cls = self._infer_object_class(obj_node)
        if obj_cls is None:
            return False
        cls_info = self._user_classes.get(obj_cls)
        if cls_info is None or not cls_info.method_asts:
            return False
        method_ast = cls_info.method_asts.get(method_name)
        if method_ast is None:
            return False
        for n in ast.walk(method_ast):
            if isinstance(n, ast.Return) and n.value is not None:
                if isinstance(n.value, ast.Tuple):
                    return True
        return False

    def _method_returns_dict(self, obj_node: ast.expr, method_name: str) -> bool:
        """Check if a class method returns a dict, by inspecting its AST."""
        obj_cls = self._infer_object_class(obj_node)
        if obj_cls is None:
            return False
        cls_info = self._user_classes.get(obj_cls)
        if cls_info is None or not cls_info.method_asts:
            return False
        method_ast = cls_info.method_asts.get(method_name)
        if method_ast is None:
            return False
        # Check dict attrs (including inherited)
        dict_attrs: set[str] = set()
        c = obj_cls
        while c and c in self._class_container_attrs:
            _, da = self._class_container_attrs[c]
            dict_attrs |= da
            c = self._user_classes[c].parent_name if c in self._user_classes else None
        for n in ast.walk(method_ast):
            if isinstance(n, ast.Return) and n.value is not None:
                if isinstance(n.value, (ast.Dict, ast.DictComp)):
                    return True
                # return self.dict_attr
                if (isinstance(n.value, ast.Attribute)
                        and isinstance(n.value.value, ast.Name)
                        and n.value.value.id == "self"
                        and n.value.attr in dict_attrs):
                    return True
        return False

    def _find_method_return_type(self, obj_node: ast.expr, method_name: str) -> ir.Type | None:
        """Try to determine the return type of a method on an object.

        First tries to identify the object's class from the AST, then looks
        up the method on that specific class (+ parents).  Falls back to a
        global scan only when the class can't be inferred.
        """
        # Try to identify the object's class
        obj_cls = self._infer_object_class(obj_node)
        if obj_cls and obj_cls in self._user_classes:
            # Search this class and its parent chain
            cls_name: str | None = obj_cls
            while cls_name and cls_name in self._user_classes:
                cls_info = self._user_classes[cls_name]
                if method_name in cls_info.methods:
                    return cls_info.methods[method_name].return_value.type
                cls_name = cls_info.parent_name
            return None
        # Fallback: walk all classes (when object class is unknown)
        for cls_info in self._user_classes.values():
            if method_name in cls_info.methods:
                return cls_info.methods[method_name].return_value.type
            parent = cls_info.parent_name
            while parent and parent in self._user_classes:
                parent_info = self._user_classes[parent]
                if method_name in parent_info.methods:
                    return parent_info.methods[method_name].return_value.type
                parent = parent_info.parent_name
        return None

    def _is_bool_typed(self, node: ast.expr) -> bool:
        """Check if an expression is boolean-typed at the AST level.

        Used to decide whether a BoolOp should produce tag BOOL vs. INT.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return True
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, tag = self.variables[node.id]
            return tag == "bool"
        if isinstance(node, ast.Compare):
            return True
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return True
        if isinstance(node, ast.BoolOp):
            return all(self._is_bool_typed(v) for v in node.values)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("bool", "isinstance"):
                return True
            if node.func.id in self._user_functions:
                return self._user_functions[node.func.id].ret_tag == "bool"
        return False

    def _class_has_method(self, class_name: str, method_name: str) -> bool:
        """Check if a class (or any ancestor) defines the given method."""
        name = class_name
        while name:
            info = self._user_classes.get(name)
            if info is None:
                return False
            if info.methods and method_name in info.methods:
                return True
            if info.method_asts and method_name in info.method_asts:
                return True
            name = info.parent_name
        return False

    def _is_obj_expr(self, node: ast.expr) -> bool:
        """Check if an expression evaluates to a user-class object."""
        if isinstance(node, ast.Name) and node.id in self.variables:
            _, type_tag = self.variables[node.id]
            return type_tag == "obj"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id in self._user_classes
        # Method calls that return an object (self or cls())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if self._infer_object_class(node) is not None:
                return True
        # Nested attribute access: obj.attr where attr is a known obj attribute
        if isinstance(node, ast.Attribute):
            if self._infer_object_class(node) is not None:
                return True
        # BinOp/UnaryOp on objects: result of __add__/__sub__/etc. is an object
        if isinstance(node, ast.BinOp):
            if self._is_obj_expr(node.left):
                return True
        if (isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.USub)
                and self._is_obj_expr(node.operand)):
            return True
        return False

    def _method_returns_self(self, obj_node: ast.expr, method_name: str) -> bool:
        """Check if a class method returns self (for fluent chains)."""
        obj_cls = self._infer_object_class(obj_node)
        if obj_cls is None:
            return False
        cls_info = self._user_classes.get(obj_cls)
        if cls_info is None or not cls_info.method_asts:
            return False
        method_ast = cls_info.method_asts.get(method_name)
        if method_ast is None:
            return False
        for n in ast.walk(method_ast):
            if (isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
                    and n.value.id == "self"):
                return True
        return False

    def _infer_constant_value_type(self, node: ast.expr) -> str | None:
        """Infer the Python type tag of a simple expression at AST level.
        Used to build per-key type maps for dict literals. Returns one of
        "int", "float", "str", "bool", or None if not statically known.
        """
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, float):
                return "float"
            if isinstance(node.value, int):
                return "int"
            if isinstance(node.value, str):
                return "str"
        if (isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)):
            v = node.operand.value
            if isinstance(v, float):
                return "float"
            if isinstance(v, int):
                return "int"
        if isinstance(node, ast.JoinedStr):
            return "str"
        return None

    def _infer_list_of_dicts_key_types(
            self, iter_node: ast.expr) -> dict[str, str] | None:
        """Given an iterable expression, try to infer a per-key type map
        that holds uniformly across every dict element.

        Accepts:
          * `ast.List` of `ast.Dict` literals (inline `[{...}, {...}]`)
          * `ast.Name` bound at module- or function-scope to such a list
            literal (scanned via `_csa_root_tree`).
          * `ast.ListComp` whose element is the outermost generator's
            loop variable (recurse into the generator's iter).
          * `ast.Name` bound to any of the above.

        Returns a `{key_str: type_tag}` dict of keys whose inferred types
        agree across all dicts in the list. Returns None if the iterable
        isn't a statically recognizable list-of-dicts. Returns an empty
        dict if the iterable is one but no keys have consistent types.
        """
        tree = getattr(self, "_csa_root_tree", None)
        visited_names: set[str] = set()

        def _collect_append_dicts(name: str) -> list[ast.Dict] | None:
            """Scan the tree for `name.append(<ast.Dict>)` calls. Returns
            the list of dict literals appended, or None if any append
            argument is a non-dict expression (meaning we can't be sure
            the list holds only dicts)."""
            if tree is None:
                return None
            dicts: list[ast.Dict] = []
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Expr)
                        and isinstance(n.value, ast.Call)):
                    continue
                call = n.value
                if not (isinstance(call.func, ast.Attribute)
                        and call.func.attr == "append"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == name
                        and len(call.args) == 1):
                    continue
                arg = call.args[0]
                if isinstance(arg, ast.Dict):
                    dicts.append(arg)
                else:
                    return None
            return dicts if dicts else None

        def resolve(node: ast.expr) -> ast.List | list[ast.Dict] | None:
            """Chase Name and ListComp references down to a sequence of
            dict literals. Returns an ast.List of dicts OR a bare list
            of ast.Dict nodes (for the empty-list + appends pattern)."""
            if isinstance(node, ast.List):
                return node
            if isinstance(node, ast.Name):
                if node.id in visited_names or tree is None:
                    return None
                visited_names.add(node.id)
                # Prefer an explicit list literal if one exists.
                for n in ast.walk(tree):
                    if (isinstance(n, ast.Assign)
                            and len(n.targets) == 1
                            and isinstance(n.targets[0], ast.Name)
                            and n.targets[0].id == node.id):
                        r = resolve(n.value)
                        if r is not None:
                            return r
                # Fall back to empty-list + append pattern: look for
                # `name = []` then `name.append({...})` throughout the
                # program. This lets the key-type inference flow through
                # lists assembled one item at a time.
                has_empty = False
                for n in ast.walk(tree):
                    if (isinstance(n, ast.Assign)
                            and len(n.targets) == 1
                            and isinstance(n.targets[0], ast.Name)
                            and n.targets[0].id == node.id
                            and isinstance(n.value, ast.List)
                            and not n.value.elts):
                        has_empty = True
                        break
                if has_empty:
                    dicts = _collect_append_dicts(node.id)
                    if dicts is not None:
                        return dicts
                return None
            if isinstance(node, ast.ListComp):
                # `[elt for loop_var in source ...]`: when elt is the
                # loop var, the output has the same element dicts as
                # the source iterable.
                if (node.generators
                        and isinstance(node.elt, ast.Name)
                        and isinstance(node.generators[0].target, ast.Name)
                        and node.generators[0].target.id == node.elt.id):
                    return resolve(node.generators[0].iter)
            return None

        resolved = resolve(iter_node)
        if resolved is None:
            return None
        # Normalize to a sequence of dict literals.
        if isinstance(resolved, ast.List):
            if not resolved.elts:
                return None
            elts: list[ast.expr] = list(resolved.elts)
        else:
            elts = list(resolved)  # list of ast.Dict nodes
        if not elts:
            return None
        per_key: dict[str, str] | None = None
        for elem in elts:
            if not isinstance(elem, ast.Dict):
                return None
            this_dict: dict[str, str] = {}
            for k_node, v_node in zip(elem.keys, elem.values):
                if not (isinstance(k_node, ast.Constant)
                        and isinstance(k_node.value, str)):
                    continue
                t = self._infer_constant_value_type(v_node)
                if t is not None:
                    this_dict[k_node.value] = t
            if per_key is None:
                per_key = this_dict
            else:
                # Intersect: keep only keys whose type agrees everywhere.
                per_key = {k: t for k, t in per_key.items()
                           if this_dict.get(k) == t}
        return per_key if per_key is not None else {}

    def _emit_subscript(self, node: ast.Subscript) -> ir.Value:
        """Emit subscript operation: s[i], s[i:j], d['key'], lst[i]."""
        # pyobj subscript: route through CPython bridge __getitem__
        if (isinstance(node.value, ast.Name)
                and node.value.id in self.variables
                and self.variables[node.value.id][1] == "pyobj"):
            obj = self._load_variable(node.value.id, node)
            if isinstance(obj.type, ir.IntType):
                obj = self.builder.inttoptr(obj, i8_ptr)
            key = self._emit_expr_value(node.slice)
            tag, data = self._bare_to_tag_data(key, node.slice)
            # Call __getitem__ via cpython_call1
            getitem = self._make_string_constant("__getitem__")
            callable_ptr = self.builder.call(
                self.runtime["cpython_getattr"], [obj, getitem])
            out_tag = self._create_entry_alloca(i32, "pysub.tag")
            out_data = self._create_entry_alloca(i64, "pysub.data")
            self.builder.call(self.runtime["cpython_call1"],
                              [callable_ptr,
                               ir.Constant(i32, tag), data,
                               out_tag, out_data])
            return self.builder.load(out_data)
        # Check for dict access
        if self._is_dict_expr(node.value):
            obj = self._emit_expr_value(node.value)
            key = self._emit_expr_value(node.slice)
            # Use FV getter; decide how to unwrap based on the dict's declared
            # value type. For unknown-value dicts, fall back to string-format
            # representation (the old dict_get_as_str behavior).
            # Fast path: int key + known int values → direct i64 return
            # (no output-pointer allocas, keeps everything in registers).
            base_name_quick = None
            bq = node.value
            while isinstance(bq, ast.Subscript):
                bq = bq.value
            if isinstance(bq, ast.Name):
                base_name_quick = bq.id
            if (isinstance(key.type, ir.IntType)
                    and base_name_quick is not None
                    and base_name_quick in self._dict_var_int_values):
                data = self.builder.call(
                    self.runtime["dict_get_int_val"], [obj, key])
                return data

            tag_slot = self._create_entry_alloca(i32, "dget.tag")
            data_slot = self._create_entry_alloca(i64, "dget.data")
            # Int keys use the int-keyed getter (native int keys in dict).
            if isinstance(key.type, ir.IntType):
                self.builder.call(self.runtime["dict_get_int_fv"],
                                  [obj, key, tag_slot, data_slot])
            elif isinstance(key.type, ir.PointerType):
                self.builder.call(self.runtime["dict_get_fv"],
                                  [obj, key, tag_slot, data_slot])
            else:
                raise CodeGenError("Dict access with non-string key not yet supported", node)
            tag = self.builder.load(tag_slot)
            data = self.builder.load(data_slot)
            # Find the base dict variable name, walking through nested
            # subscripts: d["a"]["b"] → base is "d".
            base_name = None
            base = node.value
            while isinstance(base, ast.Subscript):
                base = base.value
            if isinstance(base, ast.Name):
                base_name = base.id
            # Per-key type lookup: for mixed-value dicts, the key's type
            # was recorded at literal-assignment time. Allows `d["age"]`
            # (int) to work alongside `d["name"]` (str) in the same dict.
            if (base_name is not None
                    and base_name in self._dict_var_key_types
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                key_type = self._dict_var_key_types[base_name].get(
                    node.slice.value)
                if key_type == "int" or key_type == "bool":
                    return data
                if key_type == "float":
                    return self.builder.bitcast(data, double)
                if key_type in ("str", "list", "dict", "obj"):
                    return self.builder.inttoptr(data, i8_ptr)
            # If the dict is known to hold ints, return the data as i64
            if base_name is not None and base_name in self._dict_var_int_values:
                return data
            # If the dict is known to hold lists or dicts, return as ptr
            if base_name is not None and (
                    base_name in self._dict_var_list_values
                    or base_name in self._dict_var_dict_values):
                return self.builder.inttoptr(data, i8_ptr)
            # If the dict is known to hold objects, return the raw pointer
            if (base_name is not None
                    and base_name in getattr(self, "_dict_var_obj_values", set())):
                return self.builder.inttoptr(data, i8_ptr)
            # Unknown: use fv_str which returns the string representation for
            # non-strings and the raw pointer for strings. Matches the old
            # dict_get_as_str behavior.
            return self.builder.call(self.runtime["fv_str"], [tag, data])

        # Check for list/tuple access
        if self._is_list_expr(node.value) or self._is_tuple_expr(node.value):
            obj = self._emit_expr_value(node.value)
            if isinstance(node.slice, ast.Slice):
                return self._emit_list_slice(obj, node.slice, node)
            index = self._emit_expr_value(node.slice)
            # Route through list_get_fv and unwrap based on the static elem_type
            tag_slot = self._create_entry_alloca(i32, "lget.tag")
            data_slot = self._create_entry_alloca(i64, "lget.data")
            self.builder.call(self.runtime["list_get_fv"],
                              [obj, index, tag_slot, data_slot])
            data = self.builder.load(data_slot)
            elem_type = self._get_list_elem_type(node.value)
            if elem_type in ("str", "obj", "list", "dict"):
                return self.builder.inttoptr(data, i8_ptr)
            if elem_type == "float":
                return self.builder.bitcast(data, double)
            return data

        # Check for __getitem__ on user-class objects
        if self._is_obj_expr(node.value):
            obj_cls = self._infer_object_class(node.value)
            if obj_cls and self._class_has_method(obj_cls, "__getitem__"):
                obj = self._emit_expr_value(node.value)
                if isinstance(obj.type, ir.IntType):
                    obj = self.builder.inttoptr(obj, i8_ptr)
                key = self._emit_expr_value(node.slice)
                if isinstance(key.type, ir.PointerType):
                    key = self.builder.ptrtoint(key, i64)
                elif isinstance(key.type, ir.DoubleType):
                    key = self.builder.bitcast(key, i64)
                elif isinstance(key.type, ir.IntType) and key.type.width != 64:
                    key = self.builder.zext(key, i64)
                name_ptr = self._make_string_constant("__getitem__")
                result = self.builder.call(
                    self.runtime["obj_call_method1"],
                    [obj, name_ptr, key])
                return result

        obj = self._emit_expr_value(node.value)

        if isinstance(obj.type, ir.PointerType):
            # String indexing/slicing
            if isinstance(node.slice, ast.Slice):
                return self._emit_string_slice(obj, node.slice, node)
            else:
                index = self._emit_expr_value(node.slice)
                return self.builder.call(self.runtime["str_index"], [obj, index])

        raise CodeGenError("Subscript on unsupported type", node)

    def _emit_list_slice(self, lst: ir.Value, sl: ast.Slice, node: ast.AST) -> ir.Value:
        """Emit list slicing: lst[start:stop] or lst[start:stop:step]."""
        if sl.step is not None:
            start = self._emit_expr_value(sl.lower) if sl.lower else ir.Constant(i64, 0)
            stop = self._emit_expr_value(sl.upper) if sl.upper else ir.Constant(i64, 0)
            step = self._emit_expr_value(sl.step)
            has_start = ir.Constant(i64, 1 if sl.lower else 0)
            has_stop = ir.Constant(i64, 1 if sl.upper else 0)
            return self.builder.call(
                self.runtime["list_slice_step"],
                [lst, start, stop, step, has_start, has_stop]
            )

        start = self._emit_expr_value(sl.lower) if sl.lower else ir.Constant(i64, 0)
        stop = self._emit_expr_value(sl.upper) if sl.upper else ir.Constant(i64, 0)
        has_start = ir.Constant(i64, 1 if sl.lower else 0)
        has_stop = ir.Constant(i64, 1 if sl.upper else 0)
        return self.builder.call(
            self.runtime["list_slice"], [lst, start, stop, has_start, has_stop]
        )

    def _emit_string_slice(self, s: ir.Value, sl: ast.Slice, node: ast.AST) -> ir.Value:
        """Emit string slicing: s[start:stop]."""
        if sl.lower is not None:
            start = self._emit_expr_value(sl.lower)
            has_start = ir.Constant(i64, 1)
        else:
            start = ir.Constant(i64, 0)
            has_start = ir.Constant(i64, 0)

        if sl.upper is not None:
            stop = self._emit_expr_value(sl.upper)
            has_stop = ir.Constant(i64, 1)
        else:
            stop = ir.Constant(i64, 0)
            has_stop = ir.Constant(i64, 0)

        if sl.step is not None:
            step = self._emit_expr_value(sl.step)
            return self.builder.call(
                self.runtime["str_slice_step"],
                [s, start, stop, step, has_start, has_stop]
            )

        return self.builder.call(
            self.runtime["str_slice"], [s, start, stop, has_start, has_stop]
        )

    def _emit_list_literal(self, node: ast.List) -> ir.Value:
        """Emit a list literal [a, b, c]."""
        # Create new list
        list_ptr = self.builder.call(self.runtime["list_new"], [])

        # Append each element
        for elem_node in node.elts:
            self._emit_list_append_expr(list_ptr, elem_node)

        return list_ptr

    def _emit_list_append_expr(self, list_ptr: ir.Value, node: ast.expr) -> None:
        """Append a Python expression's value to a list via FV-ABI."""
        # For string/None/bool constants, build the FpyValue directly.
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                ptr = self._make_string_constant(node.value)
                data = self.builder.ptrtoint(ptr, i64)
                self.builder.call(self.runtime["list_append_fv"],
                                  [list_ptr, ir.Constant(i32, FPY_TAG_STR), data])
                return
            elif node.value is None:
                self.builder.call(self.runtime["list_append_fv"],
                                  [list_ptr, ir.Constant(i32, FPY_TAG_NONE),
                                   ir.Constant(i64, 0)])
                return
            elif isinstance(node.value, bool):
                val = ir.Constant(i64, 1 if node.value else 0)
                self.builder.call(self.runtime["list_append_fv"],
                                  [list_ptr, ir.Constant(i32, FPY_TAG_BOOL), val])
                return

        # Check for nested lists/tuples/comprehensions before evaluating —
        # so we can tag the append as LIST instead of STR.
        if self._is_list_expr(node) or self._is_tuple_expr(node):
            value = self._emit_expr_value(node)
            data = self.builder.ptrtoint(value, i64)
            self.builder.call(self.runtime["list_append_fv"],
                              [list_ptr, ir.Constant(i32, FPY_TAG_LIST), data])
            return
        if self._is_dict_expr(node):
            value = self._emit_expr_value(node)
            data = self.builder.ptrtoint(value, i64)
            self.builder.call(self.runtime["list_append_fv"],
                              [list_ptr, ir.Constant(i32, FPY_TAG_DICT), data])
            return
        if self._is_obj_expr(node):
            value = self._emit_expr_value(node)
            data = self.builder.ptrtoint(value, i64)
            self.builder.call(self.runtime["list_append_fv"],
                              [list_ptr, ir.Constant(i32, FPY_TAG_OBJ), data])
            return

        # For all other expressions, evaluate and dispatch by LLVM type
        value = self._emit_expr_value(node)
        self._emit_list_append_value(list_ptr, value)

    def _emit_list_append_value(self, list_ptr: ir.Value, value: ir.Value) -> None:
        """Append an LLVM value to a list via list_append_fv.

        Dispatches the tag based on the value's LLVM type. For pointers we
        assume STR (the common case); callers that know the pointer is a
        list/dict/obj should use _emit_list_append_expr with the AST node
        so the correct tag is used.
        """
        if isinstance(value.type, ir.IntType) and value.type.width == 64:
            tag = FPY_TAG_INT
            data = value
        elif isinstance(value.type, ir.IntType) and value.type.width == 32:
            tag = FPY_TAG_BOOL
            data = self.builder.zext(value, i64)
        elif isinstance(value.type, ir.DoubleType):
            tag = FPY_TAG_FLOAT
            data = self.builder.bitcast(value, i64)
        elif isinstance(value.type, ir.PointerType):
            tag = FPY_TAG_STR
            data = self.builder.ptrtoint(value, i64)
        else:
            raise CodeGenError(f"Cannot append {value.type} to list")
        self.builder.call(self.runtime["list_append_fv"],
                          [list_ptr, ir.Constant(i32, tag), data])

    def _emit_tuple_literal(self, node: ast.Tuple) -> ir.Value:
        """Emit a tuple literal (1, 2, 3). Uses FpyList internally with is_tuple=1."""
        list_ptr = self.builder.call(self.runtime["tuple_new"], [])
        for elem_node in node.elts:
            self._emit_list_append_expr(list_ptr, elem_node)
        return list_ptr

    def _emit_generator_as_list(self, node: ast.GeneratorExp) -> ir.Value:
        """Treat generator expression as eager list comprehension."""
        # GeneratorExp has the same structure as ListComp
        fake = ast.ListComp(elt=node.elt, generators=node.generators)
        ast.copy_location(fake, node)
        return self._emit_list_comprehension(fake)

    def _emit_list_comprehension(self, node: ast.ListComp) -> ir.Value:
        """Emit [expr for target in iter]."""
        if len(node.generators) > 2:
            raise CodeGenError("Only 1-2 generator list comprehensions supported", node)

        if len(node.generators) == 2:
            return self._emit_list_comprehension_nested(node)

        gen = node.generators[0]
        result_list = self.builder.call(self.runtime["list_new"], [])

        if not isinstance(gen.target, ast.Name):
            raise CodeGenError("Only simple variable targets in comprehensions", node)

        # Check if iterating over a list variable or range()
        is_range = (isinstance(gen.iter, ast.Call)
                    and isinstance(gen.iter.func, ast.Name)
                    and gen.iter.func.id == "range")

        var_name = gen.target.id

        if is_range:
            range_args = gen.iter.args
            if len(range_args) == 1:
                start = ir.Constant(i64, 0)
                stop = self._emit_expr_value(range_args[0])
                step = ir.Constant(i64, 1)
            elif len(range_args) == 2:
                start = self._emit_expr_value(range_args[0])
                stop = self._emit_expr_value(range_args[1])
                step = ir.Constant(i64, 1)
            else:
                start = self._emit_expr_value(range_args[0])
                stop = self._emit_expr_value(range_args[1])
                step = self._emit_expr_value(range_args[2])

            self._store_variable(var_name, start, "int")

            cond_block = self._new_block("lc.cond")
            body_block = self._new_block("lc.body")
            incr_block = self._new_block("lc.incr")
            end_block = self._new_block("lc.end")

            self.builder.branch(cond_block)
            self.builder.position_at_end(cond_block)
            current = self._load_variable(var_name, node)
            cond = self.builder.icmp_signed("<", current, stop)
            self.builder.cbranch(cond, body_block, end_block)

            self.builder.position_at_end(body_block)
            self._emit_lc_body(gen, node, result_list, incr_block)

            self.builder.position_at_end(incr_block)
            current = self._load_variable(var_name, node)
            incremented = self.builder.add(current, step)
            self._store_variable(var_name, incremented, "int")
            self.builder.branch(cond_block)

            self.builder.position_at_end(end_block)
        else:
            # Iterate over a list/tuple/set expression
            iter_val = self._emit_expr_value(gen.iter)
            iter_len = self.builder.call(self.runtime["list_length"], [iter_val])

            idx_name = f"__lc_idx_{var_name}"
            self._store_variable(idx_name, ir.Constant(i64, 0), "int")

            cond_block = self._new_block("lc.cond")
            body_block = self._new_block("lc.body")
            incr_block = self._new_block("lc.incr")
            end_block = self._new_block("lc.end")

            self.builder.branch(cond_block)
            self.builder.position_at_end(cond_block)
            idx = self._load_variable(idx_name, node)
            cond = self.builder.icmp_signed("<", idx, iter_len)
            self.builder.cbranch(cond, body_block, end_block)

            self.builder.position_at_end(body_block)
            idx = self._load_variable(idx_name, node)
            lc_elem_type = self._get_list_elem_type(gen.iter)
            self._fv_store_from_list(var_name, iter_val, idx, lc_elem_type)
            # If iterating over a list of dicts whose values are all ints
            # (or all lists / dicts), propagate to the loop var so
            # `p["key"]` uses the int-value path.
            if lc_elem_type == "dict":
                iter_node = gen.iter

                def _list_of_all_int_dicts(n):
                    if not isinstance(n, ast.List):
                        return False
                    if not n.elts:
                        return False
                    for e in n.elts:
                        if not isinstance(e, ast.Dict):
                            return False
                        for v in e.values:
                            if not (isinstance(v, ast.Constant)
                                    and isinstance(v.value, int)
                                    and not isinstance(v.value, bool)):
                                return False
                    return True

                if _list_of_all_int_dicts(iter_node):
                    self._dict_var_int_values.add(var_name)
                elif isinstance(iter_node, ast.Name):
                    # Look up module/function-scope assignment to check
                    # if the list was built from int-valued dict literals.
                    tree = getattr(self, "_csa_root_tree", None)
                    base_name = iter_node.id
                    if tree is not None:
                        for n2 in ast.walk(tree):
                            if (isinstance(n2, ast.Assign)
                                    and len(n2.targets) == 1
                                    and isinstance(n2.targets[0], ast.Name)
                                    and n2.targets[0].id == base_name
                                    and _list_of_all_int_dicts(n2.value)):
                                self._dict_var_int_values.add(var_name)
                                break

                # Mixed-value dict support: build a per-key type map from
                # the iterable's dict elements. Lets `p["age"] >= 30`
                # compile correctly even when `p["name"]` is a string.
                key_types = self._infer_list_of_dicts_key_types(iter_node)
                if key_types:
                    self._dict_var_key_types[var_name] = key_types

            self._emit_lc_body(gen, node, result_list, incr_block)

            self.builder.position_at_end(incr_block)
            idx = self._load_variable(idx_name, node)
            self._store_variable(idx_name, self.builder.add(idx, ir.Constant(i64, 1)), "int")
            self.builder.branch(cond_block)

            self.builder.position_at_end(end_block)

        return result_list

    def _emit_lc_body(self, gen, node, result_list, incr_block):
        """Emit the body of a list comprehension (conditions + append)."""
        for if_clause in gen.ifs:
            cond = self._emit_condition(if_clause)
            skip_block = self._new_block("lc.skip")
            append_block = self._new_block("lc.append")
            self.builder.cbranch(cond, append_block, skip_block)
            self.builder.position_at_end(skip_block)
            self.builder.branch(incr_block)
            self.builder.position_at_end(append_block)

        self._emit_list_append_expr(result_list, node.elt)
        self.builder.branch(incr_block)

    def _emit_list_comprehension_nested(self, node: ast.ListComp) -> ir.Value:
        """Emit [expr for x in outer for y in inner]."""
        gen0 = node.generators[0]
        gen1 = node.generators[1]

        if not isinstance(gen0.target, ast.Name) or not isinstance(gen1.target, ast.Name):
            raise CodeGenError("Only simple variable targets in comprehensions", node)

        result_list = self.builder.call(self.runtime["list_new"], [])

        # Outer loop setup
        is_range0 = (isinstance(gen0.iter, ast.Call) and isinstance(gen0.iter.func, ast.Name)
                     and gen0.iter.func.id == "range")

        var0 = gen0.target.id
        idx0_name = f"__nlc_idx0_{var0}"

        if is_range0:
            range_args = gen0.iter.args
            start0 = ir.Constant(i64, 0) if len(range_args) == 1 else self._emit_expr_value(range_args[0])
            stop0 = self._emit_expr_value(range_args[0] if len(range_args) == 1 else range_args[1])
            self._store_variable(var0, start0, "int")
        else:
            outer_list = self._emit_expr_value(gen0.iter)
            outer_len = self.builder.call(self.runtime["list_length"], [outer_list])
            self._store_variable(idx0_name, ir.Constant(i64, 0), "int")

        outer_cond = self._new_block("nlc.outer.cond")
        outer_body = self._new_block("nlc.outer.body")
        outer_incr = self._new_block("nlc.outer.incr")
        outer_end = self._new_block("nlc.outer.end")

        self.builder.branch(outer_cond)
        self.builder.position_at_end(outer_cond)
        if is_range0:
            cur0 = self._load_variable(var0, node)
            self.builder.cbranch(self.builder.icmp_signed("<", cur0, stop0), outer_body, outer_end)
        else:
            idx0 = self._load_variable(idx0_name, node)
            self.builder.cbranch(self.builder.icmp_signed("<", idx0, outer_len), outer_body, outer_end)

        self.builder.position_at_end(outer_body)
        if not is_range0:
            # Load element from outer list into var0
            idx0 = self._load_variable(idx0_name, node)
            # Get as list pointer (for nested list iteration like [[...], [...]])
            # Outer list contains list pointers — store as list-typed variable
            self._fv_store_from_list(var0, outer_list, idx0, "list:int")

        # Inner loop
        is_range1 = (isinstance(gen1.iter, ast.Call) and isinstance(gen1.iter.func, ast.Name)
                     and gen1.iter.func.id == "range")

        var1 = gen1.target.id

        if is_range1:
            r1args = gen1.iter.args
            start1 = ir.Constant(i64, 0) if len(r1args) == 1 else self._emit_expr_value(r1args[0])
            stop1 = self._emit_expr_value(r1args[0] if len(r1args) == 1 else r1args[1])
            self._store_variable(var1, start1, "int")
        else:
            # Iterate over list/variable
            inner_list = self._emit_expr_value(gen1.iter)
            inner_len = self.builder.call(self.runtime["list_length"], [inner_list])
            idx1_name = f"__nlc_idx_{var1}"
            self._store_variable(idx1_name, ir.Constant(i64, 0), "int")

        inner_cond = self._new_block("nlc.inner.cond")
        inner_body = self._new_block("nlc.inner.body")
        inner_incr = self._new_block("nlc.inner.incr")
        inner_end = self._new_block("nlc.inner.end")

        self.builder.branch(inner_cond)
        self.builder.position_at_end(inner_cond)
        if is_range1:
            cur1 = self._load_variable(var1, node)
            self.builder.cbranch(self.builder.icmp_signed("<", cur1, stop1), inner_body, inner_end)
        else:
            idx1 = self._load_variable(idx1_name, node)
            self.builder.cbranch(self.builder.icmp_signed("<", idx1, inner_len), inner_body, inner_end)

        self.builder.position_at_end(inner_body)
        if not is_range1:
            idx1 = self._load_variable(idx1_name, node)
            self._fv_store_from_list(var1, inner_list, idx1, "int")

        # Apply conditions and append
        self._emit_lc_body(gen1, node, result_list, inner_incr)

        self.builder.position_at_end(inner_incr)
        if is_range1:
            cur1 = self._load_variable(var1, node)
            self._store_variable(var1, self.builder.add(cur1, ir.Constant(i64, 1)), "int")
        else:
            idx1 = self._load_variable(idx1_name, node)
            self._store_variable(idx1_name, self.builder.add(idx1, ir.Constant(i64, 1)), "int")
        self.builder.branch(inner_cond)

        self.builder.position_at_end(inner_end)
        self.builder.branch(outer_incr)

        self.builder.position_at_end(outer_incr)
        if is_range0:
            cur0 = self._load_variable(var0, node)
            self._store_variable(var0, self.builder.add(cur0, ir.Constant(i64, 1)), "int")
        else:
            idx0 = self._load_variable(idx0_name, node)
            self._store_variable(idx0_name, self.builder.add(idx0, ir.Constant(i64, 1)), "int")
        self.builder.branch(outer_cond)

        self.builder.position_at_end(outer_end)
        return result_list

    def _emit_set_literal(self, node: ast.Set) -> ir.Value:
        """Emit a set literal {a, b, c} as a dict-backed hash set.

        Creates an FpyDict with keys=elements, values=None. O(1) membership.
        """
        set_ptr = self.builder.call(self.runtime["dict_new"], [])
        for elem_node in node.elts:
            val = self._emit_expr_value(elem_node)
            tag, data = self._bare_to_tag_data(val, elem_node)
            self.builder.call(self.runtime["set_add_fv"],
                              [set_ptr, ir.Constant(i32, tag), data])
        return set_ptr

    def _emit_dict_literal(self, node: ast.Dict) -> ir.Value:
        """Emit a dict literal {'a': 1, 'b': 2}.

        Routes through `dict_set_fv` so the value's exact runtime tag is
        preserved (including LIST/DICT/OBJ pointer values). The AST node
        is passed to `_bare_to_tag_data` so pointer values are tagged
        correctly rather than falling through to STR.
        """
        dict_ptr = self.builder.call(self.runtime["dict_new"], [])
        for key_node, val_node in zip(node.keys, node.values):
            # **dict unpacking: key is None in the AST
            if key_node is None:
                other = self._emit_expr_value(val_node)
                # Use dict_update to copy all entries from other into dict_ptr
                self.builder.call(self.runtime["dict_update"], [dict_ptr, other])
                continue
            key = self._emit_expr_value(key_node)
            val = self._emit_expr_value(val_node)
            tag, data = self._bare_to_tag_data(val, val_node)
            if isinstance(key.type, ir.IntType):
                # Int-keyed dict — native int-key storage
                self.builder.call(self.runtime["dict_set_int_fv"],
                                  [dict_ptr, key,
                                   ir.Constant(i32, tag), data])
            elif isinstance(key.type, ir.PointerType):
                self.builder.call(self.runtime["dict_set_fv"],
                                  [dict_ptr, key,
                                   ir.Constant(i32, tag), data])
            else:
                raise CodeGenError(
                    f"Dict literal key/value type combination not yet supported: "
                    f"{key.type}/{val.type}", node)
        return dict_ptr

    def _emit_dict_comprehension(self, node: ast.DictComp) -> ir.Value:
        """Emit {key: val for x in range(n)}."""
        if len(node.generators) != 1:
            raise CodeGenError("Only single-generator dict comprehensions supported", node)
        gen = node.generators[0]
        if not isinstance(gen.target, ast.Name):
            raise CodeGenError("Only simple variable targets in dict comprehensions", node)
        if not (isinstance(gen.iter, ast.Call) and isinstance(gen.iter.func, ast.Name)
                and gen.iter.func.id == "range"):
            raise CodeGenError("Only 'for x in range(...)' in dict comprehensions", node)

        dict_ptr = self.builder.call(self.runtime["dict_new"], [])

        range_args = gen.iter.args
        if len(range_args) == 1:
            start, stop, step = ir.Constant(i64, 0), self._emit_expr_value(range_args[0]), ir.Constant(i64, 1)
        else:
            start = self._emit_expr_value(range_args[0])
            stop = self._emit_expr_value(range_args[1])
            step = ir.Constant(i64, 1) if len(range_args) < 3 else self._emit_expr_value(range_args[2])

        var_name = gen.target.id
        self._store_variable(var_name, start, "int")

        cond_block = self._new_block("dc.cond")
        body_block = self._new_block("dc.body")
        incr_block = self._new_block("dc.incr")
        end_block = self._new_block("dc.end")

        self.builder.branch(cond_block)
        self.builder.position_at_end(cond_block)
        current = self._load_variable(var_name, node)
        cond = self.builder.icmp_signed("<", current, stop)
        self.builder.cbranch(cond, body_block, end_block)

        self.builder.position_at_end(body_block)

        # Handle filter conditions: {k: v for x in range(n) if cond}
        for if_clause in gen.ifs:
            cond_val = self._emit_condition(if_clause)
            skip_block = self._new_block("dc.skip")
            add_block = self._new_block("dc.add")
            self.builder.cbranch(cond_val, add_block, skip_block)
            self.builder.position_at_end(skip_block)
            self.builder.branch(incr_block)
            self.builder.position_at_end(add_block)

        key = self._emit_expr_value(node.key)
        val = self._emit_expr_value(node.value)
        tag, data = self._bare_to_tag_data(val, node.value)
        if isinstance(key.type, ir.IntType):
            self.builder.call(self.runtime["dict_set_int_fv"],
                              [dict_ptr, key,
                               ir.Constant(i32, tag), data])
        elif isinstance(key.type, ir.PointerType):
            self.builder.call(self.runtime["dict_set_fv"],
                              [dict_ptr, key,
                               ir.Constant(i32, tag), data])
        else:
            raise CodeGenError("Dict comprehension key/value types not yet supported", node)
        self.builder.branch(incr_block)

        self.builder.position_at_end(incr_block)
        current = self._load_variable(var_name, node)
        self._store_variable(var_name, self.builder.add(current, step), "int")
        self.builder.branch(cond_block)

        self.builder.position_at_end(end_block)
        return dict_ptr

    def _emit_ifexp(self, node: ast.IfExp) -> ir.Value:
        """Emit a ternary expression: x if condition else y."""
        cond = self._emit_condition(node.test)
        then_block = self._new_block("ifexp.then")
        else_block = self._new_block("ifexp.else")
        merge_block = self._new_block("ifexp.merge")

        self.builder.cbranch(cond, then_block, else_block)

        self.builder.position_at_end(then_block)
        then_val = self._emit_expr_value(node.body)
        then_block_end = self.builder.block
        self.builder.branch(merge_block)

        self.builder.position_at_end(else_block)
        else_val = self._emit_expr_value(node.orelse)
        else_block_end = self.builder.block
        self.builder.branch(merge_block)

        self.builder.position_at_end(merge_block)
        phi = self.builder.phi(then_val.type)
        phi.add_incoming(then_val, then_block_end)
        phi.add_incoming(else_val, else_block_end)
        return phi

    def _emit_fstring(self, node: ast.JoinedStr) -> ir.Value:
        """Emit an f-string (JoinedStr node)."""
        # Build the result by concatenating parts
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                # Literal string part
                parts.append(self._make_string_constant(value.value))
            elif isinstance(value, ast.FormattedValue):
                # {expr} part — evaluate and convert to string, applying format spec if present.
                # First extract the format spec (must be a literal string).
                spec_str = None
                if value.format_spec is not None:
                    if (isinstance(value.format_spec, ast.JoinedStr)
                            and len(value.format_spec.values) == 1
                            and isinstance(value.format_spec.values[0], ast.Constant)
                            and isinstance(value.format_spec.values[0].value, str)):
                        spec_str = value.format_spec.values[0].value
                    else:
                        raise CodeGenError("f-string format spec must be a literal", node)
                # value.conversion: -1 none, 114 ('r'), 115 ('s'), 97 ('a')
                conversion = getattr(value, 'conversion', -1)

                # Check for list/obj expressions first
                if self._is_list_expr(value.value):
                    val = self._emit_expr_value(value.value)
                    str_val = self.builder.call(self.runtime["list_to_str"], [val])
                elif self._is_dict_expr(value.value):
                    val = self._emit_expr_value(value.value)
                    str_val = self.builder.call(self.runtime["dict_to_str"], [val])
                elif self._is_tuple_expr(value.value):
                    val = self._emit_expr_value(value.value)
                    str_val = self.builder.call(self.runtime["tuple_to_str"], [val])
                elif self._is_obj_expr(value.value):
                    val = self._emit_expr_value(value.value)
                    if isinstance(val.type, ir.IntType) and val.type.width == 64:
                        val = self.builder.inttoptr(val, i8_ptr, name="obj.ptr")
                    str_val = self.builder.call(self.runtime["obj_to_str"], [val])
                elif (isinstance(value.value, ast.Attribute)
                      and isinstance(value.value.value, ast.Name)
                      and self._is_obj_expr(value.value.value)):
                    # self.attr in f-string — use obj_get_fv → fv_str
                    obj = self._emit_expr_value(value.value.value)
                    if isinstance(obj.type, ir.IntType) and obj.type.width == 64:
                        obj = self.builder.inttoptr(obj, i8_ptr, name="obj.ptr")
                    slot_idx = self._get_attr_slot(value.value)
                    if slot_idx is not None:
                        tag, data = self._emit_slot_get_direct(obj, slot_idx)
                    else:
                        tag_slot = self._create_entry_alloca(i32, "fattr.tag")
                        data_slot = self._create_entry_alloca(i64, "fattr.data")
                        attr_name = self._make_string_constant(value.value.attr)
                        self.builder.call(self.runtime["obj_get_fv"],
                                          [obj, attr_name, tag_slot, data_slot])
                        tag = self.builder.load(tag_slot)
                        data = self.builder.load(data_slot)
                    str_val = self.builder.call(self.runtime["fv_str"], [tag, data])
                else:
                    if spec_str:
                        val = self._emit_expr_value(value.value)
                        str_val = self._apply_format_spec(val, spec_str, value.value, node)
                    else:
                        # Use FV dispatch so the runtime tag drives the
                        # conversion (handles mixed-type containers).
                        fv = self._load_or_wrap_fv(value.value)
                        str_val = self._fv_call_str(fv)

                # Apply conversion if requested
                if conversion == 114:  # !r
                    # For strings, wrap in quotes. Non-strings: for now, same as str.
                    if (self._is_list_expr(value.value) or self._is_dict_expr(value.value)
                            or self._is_tuple_expr(value.value)):
                        pass  # already a string representation
                    else:
                        # Check if the underlying value is a string — wrap in repr quotes
                        val_type = None
                        if isinstance(value.value, ast.Constant) and isinstance(value.value.value, str):
                            val_type = "str"
                        elif isinstance(value.value, ast.Name) and value.value.id in self.variables:
                            _, tag = self.variables[value.value.id]
                            if tag == "str":
                                val_type = "str"
                        elif isinstance(value.value, ast.JoinedStr):
                            val_type = "str"
                        if val_type == "str":
                            str_val = self.builder.call(self.runtime["str_repr"], [str_val])
                parts.append(str_val)
            else:
                raise CodeGenError(f"Unsupported f-string part: {type(value).__name__}", node)

        if not parts:
            return self._make_string_constant("")

        # Concatenate all parts
        result = parts[0]
        for part in parts[1:]:
            result = self.builder.call(self.runtime["str_concat"], [result, part])
        return result

    def _value_to_str(self, value: ir.Value, node: ast.AST) -> ir.Value:
        """Convert an LLVM value to a string pointer (for f-string formatting)."""
        if isinstance(value.type, ir.IntType) and value.type.width == 64:
            return self.builder.call(self.runtime["int_to_str"], [value])
        elif isinstance(value.type, ir.DoubleType):
            return self.builder.call(self.runtime["float_to_str"], [value])
        elif isinstance(value.type, ir.PointerType):
            return value  # already a string
        elif isinstance(value.type, ir.IntType) and value.type.width == 32:
            # Bool — format as "True" or "False"
            true_str = self._make_string_constant("True")
            false_str = self._make_string_constant("False")
            is_true = self.builder.icmp_signed("!=", value, ir.Constant(i32, 0))
            return self.builder.select(is_true, true_str, false_str)
        raise CodeGenError(f"Cannot convert {value.type} to string", node)

    def _emit_str_format(self, node: ast.Call, fmt_str_val: ir.Value) -> ir.Value:
        """Emit str.format() by parsing the format string at compile time."""
        # The format string must be a literal for compile-time parsing
        if not (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Constant)
                and isinstance(node.func.value.value, str)):
            raise CodeGenError("str.format() requires a literal format string", node)

        fmt = node.func.value.value
        args = node.args

        # Parse format string: split on {}, {0}, {name} placeholders
        # Handle escaped braces {{ and }} which represent literal { and }
        parts: list[ir.Value] = []
        auto_idx = 0  # auto-numbering index for {}
        # First, build literal segments and placeholders
        literal_buf = []
        i = 0
        while i < len(fmt):
            c = fmt[i]
            if c == "{":
                # Check for escaped {{
                if i + 1 < len(fmt) and fmt[i + 1] == "{":
                    literal_buf.append("{")
                    i += 2
                    continue
                # Flush any pending literal
                if literal_buf:
                    parts.append(self._make_string_constant("".join(literal_buf)))
                    literal_buf = []
                # Find closing brace (accounting for format specs — but we don't support those yet)
                close = fmt.find("}", i + 1)
                if close == -1:
                    raise CodeGenError("Unclosed { in format string", node)
                field = fmt[i + 1:close]
                # Split off format spec (after colon)
                spec = ""
                if ":" in field:
                    field, spec = field.split(":", 1)
                if field == "":
                    if auto_idx >= len(args):
                        raise CodeGenError("Not enough arguments for format string", node)
                    arg_node = args[auto_idx]
                    auto_idx += 1
                elif field.isdigit():
                    idx = int(field)
                    if idx >= len(args):
                        raise CodeGenError(f"Format index {idx} out of range", node)
                    arg_node = args[idx]
                else:
                    arg_node = None
                    for kw in node.keywords:
                        if kw.arg == field:
                            arg_node = kw.value
                            break
                    if arg_node is None:
                        raise CodeGenError(f"Unknown format field: {field}", node)
                val = self._emit_expr_value(arg_node)
                if spec:
                    parts.append(self._apply_format_spec(val, spec, arg_node, node))
                else:
                    parts.append(self._format_value_to_str(val, arg_node))
                i = close + 1
                continue
            elif c == "}":
                # Escaped }}
                if i + 1 < len(fmt) and fmt[i + 1] == "}":
                    literal_buf.append("}")
                    i += 2
                    continue
                raise CodeGenError("Single } in format string (use }} for literal)", node)
            else:
                literal_buf.append(c)
                i += 1
        if literal_buf:
            parts.append(self._make_string_constant("".join(literal_buf)))

        if not parts:
            return self._make_string_constant("")

        result = parts[0]
        for part in parts[1:]:
            result = self.builder.call(self.runtime["str_concat"], [result, part])
        return result

    def _apply_format_spec(self, value: ir.Value, spec: str, arg_node: ast.expr, node: ast.AST) -> ir.Value:
        """Apply a format spec like .2f, 5d, <10 to a value, returning a string."""
        spec_ptr = self._make_string_constant(spec)
        # If the spec ends with f/e/g, treat as float
        last = spec[-1] if spec else ""
        if last in ("f", "e", "g"):
            # Convert int to float if needed
            if isinstance(value.type, ir.IntType) and value.type.width == 64:
                value = self.builder.sitofp(value, double)
            if isinstance(value.type, ir.DoubleType):
                return self.builder.call(self.runtime["format_spec_float"], [value, spec_ptr])
        # If value is a float, use float spec
        if isinstance(value.type, ir.DoubleType):
            return self.builder.call(self.runtime["format_spec_float"], [value, spec_ptr])
        # Integer format
        if isinstance(value.type, ir.IntType) and value.type.width == 64:
            return self.builder.call(self.runtime["format_spec_int"], [value, spec_ptr])
        # String format
        if isinstance(value.type, ir.PointerType):
            return self.builder.call(self.runtime["format_spec_str"], [value, spec_ptr])
        raise CodeGenError(f"Cannot apply format spec to {value.type}", node)

    def _format_value_to_str(self, value: ir.Value, node: ast.expr) -> ir.Value:
        """Convert a value to string for str.format() — reuses f-string logic."""
        if self._is_list_expr(node):
            return self.builder.call(self.runtime["list_to_str"], [value])
        if self._is_dict_expr(node):
            return self.builder.call(self.runtime["dict_to_str"], [value])
        return self._value_to_str(value, node)

    def _emit_constant_value(self, value: Any) -> ir.Value:
        """Return an LLVM value for a Python constant."""
        if isinstance(value, bool):
            return ir.Constant(i64, 1 if value else 0)
        elif isinstance(value, int):
            if value > 2**63 - 1 or value < -(2**63):
                # BigInt — represent as string
                return self._make_string_constant(str(value))
            return ir.Constant(i64, value)
        elif isinstance(value, float):
            return ir.Constant(double, value)
        elif isinstance(value, str):
            return self._make_string_constant(value)
        elif value is None:
            # None is represented as i64(0) with a special tag
            # For `is None` comparisons, we handle it at the AST level
            return ir.Constant(i64, 0)
        elif value is ...:
            # Ellipsis — represented as a sentinel value
            return ir.Constant(i64, 0)
        elif isinstance(value, bytes):
            # bytes literal — store as string for now (limited support)
            return self._make_string_constant(value.decode('latin-1', errors='replace'))
        elif isinstance(value, complex):
            # complex literal — store as float (real part only for now)
            # Full complex support would need a FPY_TAG_COMPLEX type
            return ir.Constant(double, value.real)
        else:
            raise CodeGenError(f"Unsupported constant in expression: {type(value)}")


class CodeGenError(Exception):
    """Error during code generation."""

    def __init__(self, message: str, node: ast.AST | None = None) -> None:
        self.node = node
        if node and hasattr(node, "lineno"):
            super().__init__(f"{message} (line {node.lineno})")
        else:
            super().__init__(message)
