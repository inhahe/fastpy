# Fastpy Python 3.14 Compatibility Status

Last updated 2026-04-20.

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

## Bugs fixed (2026-04-20)

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

## Known limitations (not bugs)

- **BigInt through function calls** — BigInt values passed through function
  parameters lose their BIGINT tag (treated as regular i64). Direct BigInt
  constants and variables work correctly.
- **Mixed-type dict value access** — Dict values from dynamic sources (json.loads)
  return raw i64 data. Works for int/float/str values; nested list/dict values
  need explicit subscript on the extracted value.
- **Windows x64 only** — needs MSVC Build Tools. The runtime C code is portable;
  needs Clang/GCC build scripts and ELF linking for Linux/macOS.
