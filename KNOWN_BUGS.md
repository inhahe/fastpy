# Known Bugs

Systematic audit of patterns that produce incorrect output or crash when
compiled with fastpy, compared to CPython.  All tests in the test suite
(831 tests + 400 fuzz programs) pass; the bugs below are in patterns not
yet covered by the test suite.

---

## ~~Bug 1 — `yield` in nested for-loop (inner iterates outer variable)~~

**Status:** FIXED  
**Fix:** Restructured `_gen_for_to_while` to use a "lookahead" pattern —
fetch first value before the loop, body directly at while-body level (no
if-guard), next fetch at end. The state machine now sees and handles nested
while-loops from inner for-loop conversions.

---

## ~~Bug 2 — `yield from` inside for-loop produces empty output~~

**Status:** FIXED  
**Fix:** Same lookahead pattern fix as Bug 1. Also added `ast.YieldFrom`
to `_gen_body_has_yield` so for-loops containing `yield from` are properly
recognized and converted.

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
**Status:** OPEN  
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
# Fastpy:  AttributeError: 'ctx' object has no method '__exit__'
```

**Root cause:** The `@contextmanager` decorator wraps the generator in
a CPython `_GeneratorContextManager` object. The `with` statement
dispatches to native `__enter__`/`__exit__`, but the wrapper object's
methods exist only in CPython. Fixing requires the `with` statement to
detect bridge-wrapped objects and dispatch through the CPython protocol.

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

## ~~Bug 13 — `namedtuple` repr shows plain tuple~~

**Status:** FIXED  
**Fix:** Registered `fastpy_namedtuple_print` runtime function and added
namedtuple instance detection in `_emit_print_single`. Known namedtuple
instances are printed via `namedtuple_print(tuple, type_id)` which outputs
`TypeName(field1=val1, ...)` format using the type registry.

---

## ~~Bug 14 — Abstract class instantiation doesn't raise TypeError~~

**Status:** FIXED  
**Fix:** `@abstractmethod` decorators are now tracked per class in `ClassInfo.abstract_methods`.
Abstract methods are inherited from parents unless the child provides a concrete override.
`_emit_constructor` checks for unimplemented abstract methods and raises TypeError.

---

## ~~Bug 15 — Async generator segfaults~~

**Status:** FIXED  
**Fix:** `_expand_generators` now detects `AsyncFunctionDef` nodes containing
yield and converts them to sync via `_async_to_sync` before generator expansion.
The resulting regular generator function goes through the normal state-machine
pipeline, and `async for` is stripped to regular `for` during async-to-sync.

---

## ~~Bug 16 — `self.attr = None` corrupts type inference when attr was int~~

**Status:** FIXED  
**Fix:** Rule 1 in `_detect_class_container_attrs` (which marks attrs as
`obj_attr` when assigned None) now skips attrs that also receive scalar
literal assignments (int/float) in any method. This prevents the attr read
path from misinterpreting scalar values as pointers (inttoptr segfault).
