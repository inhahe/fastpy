# Missing Python Patterns

## Previously Critical — ALL FIXED ✅

### 1. ~~ClassName.var from inside method~~ ✅
### 2. ~~**dict unpacking at call site~~ ✅
### 3. ~~*args mixed with positional params~~ ✅
### 4. ~~getattr/hasattr/setattr builtins~~ ✅
### 5. ~~Nested class method bodies~~ ✅
### 6. ~~Nested class construction `Outer.Inner()`~~ ✅
### 7. ~~Classmethod string attributes~~ ✅
### 8. ~~setattr persistence~~ ✅

## Current: Blocking native JIT compilation of Django modules

These patterns appear in Django's internal source code. When the JIT compiler
encounters them, it falls back to CPython import. Fixing these would allow
Django's modules to be compiled natively (not just bridged).

### 9. `for x in <generator_expression>` / `for x in <arbitrary_iterable>`
```python
# Django migrations/loader.py
for app_config in apps.get_app_configs():
    ...
# Django db/models/query.py  
for obj in self._iterable_class(self):
    ...
```
**Current status:** `for x in list/dict/range/string` works. `for x in pyobj` works.
But `for x in function_call_result()` where the result type is unknown at compile
time fails with "Only 'for x in range(...)' or 'for x in list/string' is supported".

**Root cause:** The for-loop dispatcher requires static type knowledge of the iterable.
When it can't determine the type (e.g., result of a bridge method call), it raises
an error instead of falling back to the pyobj iteration protocol.

**Fix:** When all static checks fail, fall back to `_emit_for_pyobj` (which uses
`fpy_cpython_iter` + `fpy_cpython_iter_next`). This is the "slow path" but correct.

### 10. `str`/`int`/`list` etc. used as type references (not calls)
```python
# Django utils/functional.py
if isinstance(value, str):
    ...
# Django forms/fields.py
validators: list[Callable] = []
```
**Current status:** `str(x)`, `int(x)`, `list(x)` work as CALLS. But when `str` is
used as a NAME reference (for isinstance, type annotations, or passed to functions),
the compiler reports "Undefined variable: str".

**Root cause:** Built-in type names (`str`, `int`, `list`, `float`, `bool`, `dict`,
`tuple`, `set`, `type`, `object`) aren't in `self.variables`. They're only handled
as special-case CALLS in `_emit_call_expr`. When used as plain Name expressions
(e.g., `isinstance(x, str)`), `_load_variable("str")` fails.

**Fix:** Add built-in type names as constants that resolve to sentinel values (e.g.,
class IDs or type tags). For `isinstance(x, str)`, the second arg just needs to be
a recognizable constant. For type annotations, they're no-ops.

### 11. Complex `try/except/else` with exception variable binding
```python
# Django db/utils.py
try:
    ...
except DatabaseError as e:
    raise SomeOtherError(...) from e
```
**Current status:** `try/except` with specific exception types works. But `as e`
(binding the exception to a variable) and `raise X from Y` (exception chaining)
aren't implemented.

**Root cause:** The exception variable binding (`as e`) requires storing the
exception object. `raise X from Y` requires `__cause__` linking which our
exception system doesn't support (we use a simple type+message model).

**Fix:** Store the exception message string as the bound variable. For `raise from`,
just ignore the `from` clause (exception chaining is for tracebacks, not behavior).

## Working patterns (verified)

- `*list` unpacking at call site ✓
- `def f(x, *rest)` mixed positional + varargs ✓
- `**dict_variable` unpacking at call site ✓
- `ClassName.var += x` from inside methods ✓
- `Outer.Inner()` nested class construction ✓
- Classmethod string attributes via cls() ✓
- getattr/hasattr/setattr ✓
- `for k,v in dict.items()` ✓
- Multiple inheritance ✓
- `super().__init__(args)` ✓
- `__contains__` (`in` operator) ✓
- try/except/finally with specific exceptions ✓
- Default argument values ✓
- `**kwargs` function with .get() returning int/str ✓
- Closures / nested functions ✓
- Generators (yield/send/close) ✓
- Decorators (@property, @classmethod, @staticmethod) ✓
- List/dict/set comprehensions ✓
- f-strings with expressions ✓
- List concatenation, dict merge, method chaining ✓
- Conditional expressions (ternary) ✓
- Chained string methods ✓
- List slicing with step, negative indexing ✓
- String multiplication, `in` on lists ✓
