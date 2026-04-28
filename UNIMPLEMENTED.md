# Fastpy Python 3.14 Compatibility Status

Last updated 2026-04-28.

## Fully native (no CPython bridge)

### Core language
Loops (for/while/break/continue/else), functions (def, lambda, recursion,
defaults, *args, **kwargs, closures, nonlocal, global), classes (init,
methods, inheritance, super, multiple inheritance, nested classes,
full metaclass support, __slots__, staticmethod, classmethod, @property
get/set, __new__, __init_subclass__, __class_getitem__), decorators
(user decorators, decorators with args), @dataclass (native AST expansion),
@singledispatch (native switch dispatch).

### Operator overloading (dunders)
__add__, __sub__, __mul__, __neg__, __eq__, __lt__, __str__, __repr__,
__getitem__, __setitem__, __delitem__, __len__, __bool__, __contains__,
__iter__/__next__, __call__, __hash__.

### Containers
list (literals, comprehensions, all methods), dict (literals, comprehensions,
get, pop, setdefault, keys, values, items, update, | merge, {**a, **b}),
tuple (literals, unpacking, *mid unpack, swap), set (literals, comprehensions,
add, discard, remove, |, &, -, ^, in — O(1) hash table), frozenset.

### Strings
f-strings (with =, !r, format specs), all common methods, % formatting,
.format(), raw strings, string multiplication, slicing, `in` operator.

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

### Silently wrong (compiles, produces incorrect results)
- **MatchStar** — `case [first, *rest]:` treated as never-match. Should capture
  remaining sequence elements.
- **MatchMapping** — `case {"key": val}:` treated as never-match. Should match
  dict structure and bind values.
- **MatchClass** — `case Point(x, y):` treated as never-match. Should match
  class instances and bind attributes. **(implemented 2026-04-28)**

### Formerly blocked, now implemented
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
  The remaining gap is unannotated parameters: `def find_root(d): return
  d.resolve()` still fails because the codegen can't know `d` is a Path.
  **Planned fix:** Runtime tag-based method dispatch — when calling a method
  on an FV-backed variable with unknown compile-time type, check the runtime
  tag and dispatch to `cpython_getattr` + `cpython_call` for OBJ-tagged values.

- **BigInt through function calls** — BigInt values passed through function
  parameters lose their BIGINT tag (treated as regular i64). Direct BigInt
  constants and variables work correctly. Same root cause as above: no
  interprocedural type inference.

- **Return type annotations ignored** *(fixed)* — `-> str` on function
  definitions now propagates to `ret_tag`, so call sites see the correct
  type. Supports scalar types (int, float, str, bool), containers
  (list, dict, set, tuple), user classes, None, and bridge types (Path).
  See bug 34.

- **Mixed-type dict value access** — Dict values from dynamic sources (json.loads)
  return raw i64 data. Works for int/float/str values; nested list/dict values
  need explicit subscript on the extracted value.

### Object model

- **Fastpy objects are not PyObjects** — CPython cannot treat fastpy-compiled
  functions, classes, or instances as `PyObject*`. Passing fastpy callables
  (lambdas, closures) to CPython APIs that expect Python callables fails.
  This affects `functools.reduce(lambda ...)`, `collections.defaultdict(int)`,
  and similar patterns. Workaround: use CPython-side
  callables or avoid bridge calls that need fastpy values as callbacks.
  **Planned fix (mirror object pattern):**
  Add an optional `PyObject* py_mirror` field to FpyObj. When a native object
  is passed to CPython, lazily create a PyObject* wrapper backed by a custom
  PyTypeObject (`FpyWrapperType`) that delegates `tp_getattro`, `tp_setattro`,
  `tp_call`, `tp_richcompare`, and `tp_hash` back to the FpyObj's slot system.
  Cache the wrapper in `py_mirror` for identity preservation. For the reverse
  direction (PyObject* → FpyObj), store the original PyObject* pointer in an
  optional `py_origin` field so round-trips preserve identity. For functions
  and lambdas, `cpython_wrap_native` already creates PyCFunction wrappers —
  extend this to class instances and arbitrary objects.

- **PyObject* values in FpyValue OBJ tag are not FpyObj** *(mostly fixed)* —
  CPython PyObject* (e.g. `pathlib.Path`) stored in FpyValue with OBJ tag.
  The runtime `fastpy_obj_write` checks the magic field (`FPY_OBJ_MAGIC`)
  to distinguish native FpyObj* from CPython PyObject* and routes to
  `fpy_cpython_print_obj` for the latter. `fpy_value_repr` has the same
  check. Multi-arg print (`print("x:", p)`) works correctly via the
  `_load_or_wrap_fv` → `cpython_to_fv` → `fv_write` → magic check path.
  Remaining edge case: `fv_cmp` and `fv_truthy` don't distinguish the two
  (minor: truthy works because `data != 0` is correct for both; comparison
  may produce wrong results for PyObject* values).

### Bridge

- **Bridge dict mutation silently dropped** *(fixed)* — Passing an FpyDict to
  a CPython function now syncs mutations back. `fpy_sync_pydict_to_fpydict`
  clears and rebuilds the FpyDict from the mutated PyDict after every bridge
  call. Handles add/modify/delete, rehashes index table on growth. Added to
  all call variants (1-arg, 2-arg, 3-arg, N-arg) alongside existing list
  sync-back. See bug 36.

### Source merger

- **Packages cannot be merged** — Only single-file stdlib modules can be
  source-merged. Packages with `__init__.py` and submodules are skipped
  entirely and fall back to the CPython bridge. This is because the merger
  operates on individual .py files; resolving intra-package imports and
  prefixing across multiple files is not implemented.

- **C-extension wrapper modules rejected** — Stdlib modules whose public
  API comes from `from _foo import *` (e.g. `ast`, `collections`, `json`,
  `operator`, `functools`) cannot be source-merged. The merger's name
  prefixing (`ast__Constant`) fails because star-imported names are not
  enumerable at compile time. Detected by `_is_c_extension_wrapper()` in
  `stdlib_cache.py`.

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
- Functions that receive Path/PyObject* parameters and call methods on them
  crash (no interprocedural type inference — see above).
  Example: `_find_project_root(base_dir)` receives a Path, calls
  `.resolve()` and `/ "__init__.py"` on it — the callee can't dispatch these.
- The pipeline functions use extensive dynamic typing (dicts of mixed types,
  AST node manipulation, `isinstance` checks) that requires the CPython
  bridge for every operation on untyped parameters.
