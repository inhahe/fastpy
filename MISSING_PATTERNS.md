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

## Previously Blocking Django -- ALL FIXED

### 9. ~~`for x in <generator_expression>` / `for x in <arbitrary_iterable>`~~ FIXED
For-loop dispatcher now falls back to `_emit_for_pyobj` (using
`fpy_cpython_iter` + `fpy_cpython_iter_next`) when the iterable type
is unknown at compile time. Works for function call results, generator
expressions, and arbitrary iterables.

### 10. ~~`str`/`int`/`list` etc. used as type references~~ FIXED
Built-in type names are now recognized as first-class values. Works in
isinstance() checks, as function arguments, and in type annotations (no-ops).
Part of the first-class functions / bridge fallback work.

### 11. ~~Complex `try/except/else` with exception variable binding~~ FIXED
Exception variable binding (`except X as e`) and `raise X from Y` (exception
chaining) are now implemented. The `as e` variable stores the exception
message string. `raise from` preserves the chain for tracebacks.

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
