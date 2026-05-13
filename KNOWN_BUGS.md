# Known Bugs

Systematic audit of patterns that produce incorrect output or crash when
compiled with fastpy, compared to CPython.  All tests in the test suite
(831 tests + 400 fuzz programs) pass; the bugs below are in patterns not
yet covered by the test suite.

---

## Bug 1 — `yield` in nested for-loop (inner iterates outer variable)

**Severity:** Wrong output  
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

## Bug 3 — Multiple `except*` clauses: only first runs

**Severity:** Wrong output  
**Pattern:**
```python
try:
    raise ExceptionGroup("e", [ValueError("a"), TypeError("b")])
except* ValueError:
    print("caught ValueError")
except* TypeError:
    print("caught TypeError")
# CPython: prints both
# Fastpy:  only prints "caught ValueError"
```

**Root cause:** The `except*` (TryStar) handler implementation processes
exception groups but only matches the first handler, then exits the
try-block instead of continuing to match remaining unhandled exceptions
against subsequent handlers.

---

## Bug 4 — Match statement: second list-pattern case crashes

**Severity:** Crash (exit code 1)  
**Pattern:**
```python
x = ["b", "hello"]
match x:
    case ["a", y]:
        print(y)
    case ["b", y]:
        print(y + "!")
# CPython: hello!
# Fastpy:  crash (exit 1)
```

**Root cause:** When a match statement has multiple cases with sequence
(list) patterns, falling through from a non-matching first case to the
second case fails.  The pattern matching variables or list unpacking state
from the first case likely corrupts the state needed for the second case.

---

## Bug 5 — `with` statement with comma-separated contexts segfaults

**Severity:** Segfault (access violation)  
**Pattern:**
```python
with Ctx(1) as a, Ctx(2) as b:
    print(a.n, b.n)
# CPython: works
# Fastpy:  segfault (exit 3221225477)
```

**Root cause:** Multiple context managers in a single `with` statement
(`with A as a, B as b:`) are likely not handled — only the first context
manager is processed.

---

## Bug 6 — `hasattr()` returns True for missing attributes

**Severity:** Wrong output  
**Pattern:**
```python
class Obj:
    def __init__(self):
        self.x = 1
o = Obj()
print(hasattr(o, "y"))
# CPython: False
# Fastpy:  True
```

**Root cause:** `hasattr()` implementation doesn't properly catch
`AttributeError` when the attribute doesn't exist — it always returns True.

---

## Bug 7 — `getattr()` with default crashes on missing attribute

**Severity:** Crash (exit code 1)  
**Pattern:**
```python
class Obj:
    pass
o = Obj()
print(getattr(o, "x", "default"))
# CPython: default
# Fastpy:  crash
```

**Root cause:** The 3-argument form of `getattr(obj, name, default)` doesn't
catch `AttributeError` and return the default — it lets the error propagate.

---

## Bug 8 — `issubclass()` crashes for user-defined classes

**Severity:** Crash (exit code 1)  
**Pattern:**
```python
class A:
    pass
class B(A):
    pass
print(issubclass(B, A))
# CPython: True
# Fastpy:  crash
```

**Root cause:** `issubclass()` works for builtin types (`issubclass(bool,
int)`) but not for user-defined classes.  The class hierarchy traversal
likely doesn't handle user class objects.

---

## Bug 9 — `next()` with default crashes when iterator exhausted

**Severity:** Crash (exit code 1)  
**Pattern:**
```python
it = iter([1])
print(next(it))
print(next(it, "done"))
# CPython: 1, done
# Fastpy:  1, crash
```

**Root cause:** The 2-argument form of `next(iterator, default)` doesn't
catch `StopIteration` and return the default — it lets the exception
propagate.

---

## Bug 10 — `contextlib.contextmanager` doesn't work

**Severity:** Crash (exit code 1)  
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

## Bug 11 — Property deleter causes compiler crash

**Severity:** Compiler crash (DuplicatedNameError)  
**Pattern:**
```python
class C:
    @property
    def x(self):
        return self._x
    @x.setter
    def x(self, val):
        self._x = val
    @x.deleter
    def x(self):
        self._x = None
```

**Root cause:** The `@x.deleter` decorator causes the compiler to try to
register a function named `fastpy.class.C.x` twice — the property getter
and deleter collide on the same LLVM function name.

---

## Bug 12 — `__mro__` access segfaults

**Severity:** Segfault  
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
