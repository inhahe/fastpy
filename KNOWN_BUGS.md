# Known Bugs

Systematic audit of patterns that produce incorrect output or crash when
compiled with fastpy, compared to CPython.  All tests in the test suite
(831 tests + 400 fuzz programs) pass; the bugs below are in patterns not
yet covered by the test suite.

---

## Bug 1 — `yield` in nested for-loop (inner iterates outer variable)

**Severity:** Wrong output  
**Status:** OPEN  
**Pattern:**
```python
def g():
    data = [[1,2],[3,4]]
    for sub in data:
        for x in sub:
            yield x
print(list(g()))
# CPython: [1, 2, 3, 4]
# Fastpy:  [1, 3]  (only first element per outer iteration)
```

**Root cause:** `_gen_for_to_while` wraps the preprocessed for-loop body in
an `if not _done:` guard.  When the body contains a nested while-loop with
yield (from the inner for-loop's conversion), the state machine in
`_gen_split_stmts` doesn't recurse into the if-body to handle the inner
while-loop.  The inner loop's iterator state isn't saved across yields.

**Fix plan:** Restructure `_gen_for_to_while` to use a "lookahead" pattern
that keeps the loop body at the top level of the while-loop body (no
if-guard), so the state machine can see and handle nested while-loops.

---

## Bug 2 — `yield from` inside for-loop produces empty output

**Severity:** Wrong output  
**Status:** OPEN  
**Pattern:**
```python
def g():
    data = [[1,2],[3,4]]
    for sub in data:
        yield from sub
print(list(g()))
# CPython: [1, 2, 3, 4]
# Fastpy:  []
```

**Root cause:** Same as Bug 1.  The `yield from` expansion creates a
while-loop with yield, which gets wrapped in the if-guard and hidden from
the state machine.

**Fix plan:** Same as Bug 1 — the lookahead pattern fix resolves both.

---

## ~~Bug 3 — Multiple `except*` clauses: only first runs~~

**Status:** FIXED  
**Fix:** Pre-compute all handler match results while exception state is live,
clear exception, then run ALL matching handler bodies sequentially.
Runtime expanded to track multiple inner exception types per ExceptionGroup.

---

## ~~Bug 4 — Match statement: second list-pattern case crashes~~

**Status:** FIXED  
**Fix:** Match capture patterns (MatchAs) now store variables with
`VKind.FVALUE` instead of `VKind.INT`, preserving the runtime type tag
so captured values dispatch correctly in operations like `y + "!"`.

---

## ~~Bug 5 — `with` statement with comma-separated contexts segfaults~~

**Status:** FIXED  
**Fix:** Multiple context managers (`with A as a, B as b:`) are now desugared
into nested `with` statements before processing, matching Python semantics.

---

## ~~Bug 6 — `hasattr()` returns True for missing attributes~~

**Status:** FIXED  
**Fix:** Added `fastpy_obj_has_attr` runtime function that checks both static
slots and dynamic attrs without raising. Codegen now calls this instead of
returning constant `True`.

---

## ~~Bug 7 — `getattr()` with default crashes on missing attribute~~

**Status:** FIXED  
**Fix:** Added `fastpy_obj_getattr_default` runtime function. Codegen handles
the 3-argument form of `getattr(obj, name, default)` by calling this function.

---

## ~~Bug 8 — `issubclass()` crashes for user-defined classes~~

**Status:** FIXED  
**Fix:** Implemented native `issubclass()` that resolves at compile time by
walking the `parent_name` chain in ClassInfo. Also handles builtin type
relationships like `issubclass(bool, int)`.

---

## ~~Bug 9 — `next()` with default crashes when iterator exhausted~~

**Status:** FIXED  
**Fix:** The 2-argument `next(iterator, default)` now checks for pending
StopIteration after `__next__()` call, clears it, and returns the default
value via a phi node.

---

## Bug 10 — `contextlib.contextmanager` doesn't work

**Severity:** Crash (exit code 1)  
**Status:** OPEN (depends on Bugs 1-2)  
**Pattern:**
```python
from contextlib import contextmanager

@contextmanager
def ctx(name):
    print("enter", name)
    yield name
    print("exit", name)

with ctx("test") as val:
    print("inside", val)
# CPython: enter test / inside test / exit test
# Fastpy:  crash
```

**Root cause:** Likely related to the generator bugs (Bugs 1-2) and/or
how the contextmanager decorator interacts with the generator protocol.

---

## ~~Bug 11 — Property deleter causes compiler crash~~

**Status:** FIXED  
**Fix:** Property deleters are now compiled as `x__del` functions (like
setters use `x__set`). `del obj.prop` dispatches to the deleter method.

---

## Bug 12 — `__mro__` access segfaults

**Severity:** Segfault  
**Status:** OPEN  
**Pattern:**
```python
class D(B, C):
    pass
print([cls.__name__ for cls in D.__mro__])
# CPython: ['D', 'B', 'C', 'A', 'object']
# Fastpy:  segfault
```

**Root cause:** Accessing `__mro__` on a class object likely returns an
invalid pointer or unsupported type, causing a segfault when iterated.

---

## Bug 13 — `namedtuple` repr shows plain tuple

**Severity:** Wrong output  
**Status:** OPEN  
**Pattern:**
```python
from collections import namedtuple
Point = namedtuple("Point", ["x", "y"])
p = Point(3, 4)
print(p)
# CPython: Point(x=3, y=4)
# Fastpy:  (3, 4)
```

**Root cause:** The namedtuple's custom `__repr__` isn't invoked — the
object is treated as a plain tuple for string conversion.

---

## Bug 14 — Abstract class instantiation doesn't raise TypeError

**Severity:** Wrong output (missing error)  
**Status:** OPEN  
**Pattern:**
```python
from abc import ABC, abstractmethod
class Shape(ABC):
    @abstractmethod
    def area(self):
        pass
Shape()  # Should raise TypeError
# CPython: TypeError: Can't instantiate abstract class ...
# Fastpy:  no error
```

**Root cause:** The ABC metaclass enforcement isn't implemented — abstract
classes can be instantiated without implementing abstract methods.

---

## Bug 15 — Async generator segfaults

**Severity:** Segfault  
**Status:** OPEN  
**Pattern:**
```python
async def agen():
    for i in range(3):
        yield i

async def main():
    async for x in agen():
        print(x)
```

**Root cause:** Async generators (`async def` with `yield`) aren't fully
supported.  The `async for` protocol likely doesn't handle the async
generator object correctly.

---

## Bug 16 — `self.attr = None` corrupts type inference when attr was int

**Severity:** Segfault / wrong output  
**Status:** OPEN  
**Pattern:**
```python
class C:
    def __init__(self):
        self._x = 10
    def reset(self):
        self._x = None

c = C()
c._x = 42
print(c._x)
# CPython: 42
# Fastpy:  segfault
```

**Root cause:** When any method assigns `None` to an attribute that was
initialized as `int` in `__init__`, the static type inference for that
attribute's slot may be corrupted (slot type changes from int to
None/mixed), causing the setter to write to the wrong slot type or the
getter to misinterpret the stored value.
