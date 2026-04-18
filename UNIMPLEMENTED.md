# Unimplemented Python 3.14 Patterns

Status: **43/66** tested patterns working (65% coverage).

Last updated after Phase 28 (dunder methods, match/case, print(*list),
dict comp filter, bare raise, bytes).

## Currently working (43 features)

Loops, functions (def, lambda, recursion, defaults, *args, closures),
classes (init, methods, inheritance, super, multiple inheritance),
operator overloading (__add__, __sub__, __mul__, __neg__, __eq__, __lt__,
__str__, __repr__, __getitem__, __len__, __bool__, __contains__, __call__,
__hash__, __delitem__),
containers (list, dict, tuple, set, comprehensions with filters),
strings (f-strings, methods, slicing, %, .format),
exceptions (try/except/finally, raise, bare raise, multiple except types),
imports (import module, from module import name — .pyd support),
control flow (if/elif/else, break, continue, ternary, walrus, match/case),
with statement, chained comparisons, augmented assign, global,
type hints (ignored at runtime), print(*list), bytes (basic len).

## Still missing (23 features)

### 1. Generators & Iterators (4 features)

**yield / yield from / generator expressions / send+next**
```python
def gen():
    yield 1
    yield 2
for x in gen():
    print(x)
```
Requires transforming generator functions into resumable state machines.
This is the largest single missing feature. Generator expressions as
standalone iterables also don't work (they do work inside sum/any/all).

### 2. Async / Await (2 features)

```python
async def f():
    await asyncio.sleep(0)
    return 1
```
Requires async runtime, event loop integration, coroutine objects.

### 3. Dunder methods — remaining gaps (4 features)

**__setitem__** — dispatches to the method but value coercion is wrong
(string keys get garbled). Needs fixing in argument passing.

**__iter__ / __next__** — iterator protocol. `for x in custom_obj`
doesn't call `__iter__`/`__next__`. Blocked by: `raise StopIteration`
not supported as a bare expression (only in try/except context).

**__call__ on constructor result** — `C()(5)` where the Call target is
itself a Call expression. The pipeline allows it but codegen doesn't
handle `ast.Call` as `node.func`.

### 4. Property / Descriptors (2 features)

```python
class C:
    @property
    def x(self): return self._x
    @x.setter
    def x(self, v): self._x = v
```
`@property` is recognized as a decorator but attribute access doesn't
dispatch to the getter/setter. Needs special handling in `_emit_attr_load`
and `_emit_attr_store` for property-decorated methods.

### 5. User Decorators (2 features)

```python
@my_decorator
def f(a, b): return a + b
```
Blocked by: `*args` not fully supported in nested function definitions
(decorator wrappers typically use `def wrapper(*args, **kwargs)`).

### 6. Star Expressions — remaining gaps (1 feature)

**`f(**dict)` call** — `**kwargs` unpacking in function calls doesn't
work correctly. `print(*list)` works. `f(*list)` works.

### 7. Types — remaining gaps (3 features)

- **complex** — `1+2j` not supported as constant
- **bytearray** — `bytearray()` not implemented as builtin
- **frozenset** — `frozenset()` not implemented as builtin

### 8. Class Features — remaining gaps (2 features)

- **Nested classes** — `Outer.Inner` not recognized as class access
- **Metaclasses** — `class C(metaclass=M)` crashes

### 9. Exceptions — remaining gaps (1 feature)

- **except\*** (Exception Groups, Python 3.11+) — `TryStar` not implemented

### 10. Other (2 features)

- **nonlocal write-back** — partially broken for some closure patterns
- **ellipsis `is` check** — `x is ...` not supported (`is` only handles None)

## Priority order for implementation

1. **Generators/yield** — used everywhere, largest single gap
2. **__iter__/__next__** — iterator protocol for custom classes
3. **@property** — standard Python OOP
4. **User decorators** — needs *args in nested functions
5. **__setitem__ fix** — argument coercion bug
6. **Nested classes** — relatively easy
7. **nonlocal fix** — closure write-back bug
8. **async/await** — needed for async programs
9. **complex/bytearray/frozenset** — type support
10. **except\*, metaclasses** — advanced features
