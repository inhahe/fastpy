# Unimplemented Python 3.14 Patterns

Status: **66/66** audit features working + **62/62** extended pattern tests (100% coverage).

Last updated 2026-04-19 after implementing all 6 remaining audit features
(async/await, send-to-gen, except*, bytearray, metaclass) and refactoring
sets to use O(1) hash tables.

## Currently working

### Core language
Loops (for/while/break/continue/else), functions (def, lambda, recursion,
defaults, *args, **kwargs, closures, nonlocal, global), classes (init,
methods, inheritance, super, multiple inheritance, nested classes,
metaclass, __slots__, staticmethod, classmethod, @property get/set),
decorators (user decorators, decorators with args).

### Operator overloading (dunders)
__add__, __sub__, __mul__, __neg__, __eq__, __lt__, __str__, __repr__,
__getitem__, __setitem__, __delitem__, __len__, __bool__, __contains__,
__iter__/__next__, __call__, __hash__.

### Containers
list (literals, comprehensions, all methods: append, pop, remove, insert,
index, count, sort, reverse, extend, copy, clear),
dict (literals, comprehensions, get, pop, setdefault, keys, values, items,
update, | merge, {**a, **b} unpacking),
tuple (literals, unpacking, *mid unpack, swap),
set (literals, comprehensions, add, discard, remove, |, &, -, ^, in —
all backed by O(1) hash table),
frozenset (via CPython bridge).

### Strings
f-strings (with =, !r, format specs), methods (split, join, replace,
strip, startswith, endswith, find, upper, lower, count, format, isdigit,
title, capitalize), raw strings, string multiplication, slicing,
% formatting, `in` operator.

### Exceptions
try/except/finally/else, raise, bare raise, raise from, multiple except
types, except* (ExceptionGroup).

### Generators & Iterators
yield, yield from, generator expressions, send/close/throw (via CPython
bridge for coroutine-style generators), iterator protocol (__iter__/__next__).

### Async
async def, await (via CPython bridge — async function bodies run in
CPython's asyncio runtime).

### Pattern matching
match/case with literal, capture, guard, or, wildcard, sequence patterns.

### Imports
import module, from module import name (.pyd support via CPython bridge).

### Builtins
print, range, len, sorted, int, abs, sum, min, max, list, reversed, set,
enumerate, zip, isinstance (including tuple of types), str, type, any,
all, bool, float, chr, ord, hex, oct, bin, round, repr, pow, divmod,
dict, tuple, map, filter, hash, next, iter, bytearray, frozenset,
complex, slice, getattr, setattr, hasattr, delattr.

### Control flow & misc
if/elif/else, ternary, walrus operator, chained comparisons, with
statement, assert, type hints (ignored), ellipsis, global/nonlocal,
for/else, while/else, try/else.

### Threading
Three modes via CLI flags:
- `--threading none` (default): single-threaded, no overhead
- `--threading gil`: GIL mode, one thread runs compiled code at a time
- `--threading free` or `-t`: free-threaded, per-object locks, true parallelism

`threading.Thread(target=compiled_func)` works — compiled functions are
auto-wrapped as CPython callables via `fpy_cpython_wrap_native`.
Thread-local exception state and per-thread bump allocators.

## Known limitations (not bugs — architectural constraints)

These are patterns that work partially or through fallback paths:

1. **Generators with send()** use CPython bridge — the function body runs
   in CPython rather than as native compiled code. Simple yield/yield-from
   generators compile natively via list collection.

2. **Async functions** run entirely in CPython via the bridge. No native
   async compilation.

3. **Metaclass support** is simplified — `type(C).__name__` is resolved at
   compile time. Full metaclass instantiation protocol not implemented.

4. **map()** with closures that capture variables works for variable-backed
   function pointers but not for magic-number closures.

5. **Complex numbers** route through CPython bridge — no native complex
   arithmetic.

6. **eval()/exec()** — `eval("literal")` pre-compiles via CPython bridge.
   Dynamic eval (non-literal strings) routes through `builtins.eval`.
   `exec()` with literal strings works similarly. Neither has access to
   the compiled program's local variables.

7. **Multiple dispatch / singledispatch** not supported.

8. **Dataclasses, NamedTuple** not supported (would need decorator processing).

9. **CPython bridge result arithmetic with `np.mean` style** — printing a
   numpy float64 scalar directly shows the result via CPython's `str()`, but
   using it in float arithmetic or `float()` conversion doesn't detect it
   as a float (treated as OBJ tag → pointer garbage).

10. **Threading: compiled functions with args** — `threading.Thread(target=func)`
    works for zero-arg functions. Functions with parameters need the native
    wrapper to handle argument passing (currently only `void(*)(void)` ABI).

### Recently resolved (2026-04-19)

- **#4 filter()** — now uses inline loop like map(), handles all element types
- **#10 Context managers** — `__enter__`/`__exit__` dispatch works
- **#11 int() on 2+ arg bridge calls** — `int(np.dot(a,b))` now works
- **#13 sorted(key=user_func) on strings** — call-site analysis traces through sorted/min/max
- **#15 Shared mutable state** — global lists/dicts/strings work across functions
- **#16 Per-object locking** — complete coverage on all mutating list/dict operations
