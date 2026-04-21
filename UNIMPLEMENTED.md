# Fastpy Python 3.14 Compatibility Status

Last updated 2026-04-21.

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
match/case with literal, capture, guard, or, wildcard, sequence patterns.

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

## Known limitations (not bugs)

- **BigInt through function calls** — BigInt values passed through function
  parameters lose their BIGINT tag (treated as regular i64). Direct BigInt
  constants and variables work correctly.
- **Mixed-type dict value access** — Dict values from dynamic sources (json.loads)
  return raw i64 data. Works for int/float/str values; nested list/dict values
  need explicit subscript on the extracted value.
- **Fastpy objects are not PyObjects** — CPython cannot treat fastpy-compiled
  functions, classes, or instances as `PyObject*`. Passing fastpy callables
  (lambdas, closures) to CPython APIs that expect Python callables fails.
  This affects `functools.reduce(lambda ...)`, `collections.defaultdict(int)`,
  `weakref.ref(...)`, and similar patterns. Workaround: use CPython-side
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
- **Bridge mutation is silently dropped** — Passing an FpyList or FpyDict to
  a CPython function creates a copy. In-place mutations (e.g. `heapq.heapify`,
  `struct.pack_into`) happen on the copy and are discarded. Workaround: capture
  the return value instead of relying on in-place mutation.
  **Planned fix (copy + sync-back):** True shared backing is impossible because
  CPython C extensions use macros (`PyList_GET_ITEM`, `PyDict_Next`) that
  directly access `PyListObject->ob_item[]` / `PyDictObject` internals,
  bypassing any custom type's protocol methods. The element representations
  are also incompatible (FpyValue is 16 bytes, PyObject* is 8 bytes).
  Instead, after each bridge call, for each LIST/DICT argument that was
  passed to CPython, re-read the PyList/PyDict contents back into the
  original FpyList/FpyDict. Implementation: in `fpy_cpython_call_kw` (and
  the call0/1/2/3 variants), after `PyObject_Call` returns, iterate the
  mutable args: if tag==LIST, clear the FpyList and re-append from the
  PyList; if tag==DICT, clear and re-insert from PyDict. This is O(n) per
  mutable arg but the copy-out is already O(n), so total cost doubles but
  order doesn't change. For bytearrays (pack_into), the same pattern
  applies: copy the PyByteArray buffer back into the FpyValue.
