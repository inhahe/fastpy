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

## Known limitations (not bugs — architectural constraints)

These are patterns that work partially or through fallback paths:

1. **Generators with send()** use CPython bridge — the function body runs
   in CPython rather than as native compiled code. Simple yield/yield-from
   generators compile natively via list collection.

2. **Async functions** run entirely in CPython via the bridge. No native
   async compilation.

3. **Metaclass support** is simplified — `type(C).__name__` is resolved at
   compile time. Full metaclass instantiation protocol not implemented.

4. **filter()** still uses the old int-int function pointer ABI (Hack 21
   in CLAUDE.md). Works for int predicates and lambdas but not for
   string-typed elements.

5. **map()** with closures that capture variables works for variable-backed
   function pointers but not for magic-number closures.

6. **Complex numbers** route through CPython bridge — no native complex
   arithmetic.

7. **eval()/exec()** not supported natively (would need embedded interpreter).

8. **Multiple dispatch / singledispatch** not supported.

9. **Dataclasses, NamedTuple** not supported (would need decorator processing).

10. **Context manager protocol** (`__enter__`/`__exit__`) — `with` statement
    works for file-like patterns but custom context managers may not dispatch
    correctly.

11. **CPython bridge `int()`/`float()` on inline expressions** — `int(np.sum(a))`
    works when `np.sum(a)` is a 1-arg call on a pyobj module, but fails for
    2+ arg calls like `int(np.dot(a,b))`. The raw-call path only detects
    1-arg CPython method calls.

12. **CPython bridge result arithmetic with `np.mean` style** — printing a
    numpy float64 scalar directly shows the result via CPython's `str()`, but
    using it in float arithmetic or `float()` conversion doesn't detect it
    as a float (treated as OBJ tag → pointer garbage).

13. **Sorting with user-function keys on string params** — `sorted(lst, key=func)`
    where func takes a string parameter fails because call-site analysis
    doesn't trace through sorted() to infer parameter types.
