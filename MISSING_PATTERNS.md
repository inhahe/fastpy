# Missing Python Patterns

## Critical — ALL FIXED ✅

### 1. ~~ClassName.var from inside method~~ ✅
`_class_var_is_mutated` now detects AugAssign (`Counter.count += 1`).

### 2. ~~**dict unpacking at call site~~ ✅
Both `_emit_user_call` paths expand `**variable` by searching module stmts.

### 3. ~~*args mixed with positional params~~ ✅
`def f(x, *rest)` now compiles: positional args filled first, rest packed to list.

### 4. ~~getattr/hasattr/setattr builtins~~ ✅
Implemented via `obj_get_fv`/`obj_set_fv` for native objects.

### 5. ~~Nested class method bodies~~ ✅
`_emit_class_methods` recurses into nested ClassDef. Linkage set at body emission.

## Remaining Edge Cases

### 6. Nested class construction via attribute: `Outer.Inner()`
```python
class Outer:
    class Inner:
        def val(self):
            return 42

i = Outer.Inner()  # SEGFAULT: attribute-based class resolution not wired to constructor
```
**Root cause:** `Outer.Inner()` is `Call(Attribute(Name("Outer"), "Inner"))`. The call
dispatcher doesn't resolve chained class names to constructors. Only direct `Inner()`
or `ClassName()` works.

### 7. String attributes lost through classmethod construction
```python
class User:
    def __init__(self, name, admin):
        self.name = name
        self.admin = admin
    @classmethod
    def create_admin(cls, name):
        return cls(name, True)

admin = User.create_admin("root")
print(admin.name)  # Prints raw pointer instead of "root"
```
**Root cause:** Classmethod parameters are i64 (raw data without tag). When passed
to `cls(name, True)` → `__init__`, the string "root" arrives as i64 without STR tag.
`__init__` stores it with INT tag. The fix requires classmethods to carry FpyValue
parameters or re-tag at the constructor call.

### 8. setattr value not persisting
```python
obj = Obj()
setattr(obj, "x", 99)
print(obj.x)  # Still prints original value, not 99
```
**Root cause:** `obj_set_fv` writes to the object's slot, but the print path may
load from a cached/inlined value from `__init__` instead of re-reading the slot.

## Working patterns (verified)

- `*list` unpacking at call site: `func(*[1,2,3])` ✓
- `def f(x, *rest)` mixed positional + varargs ✓
- `**dict_variable` unpacking at call site ✓
- `ClassName.var += x` from inside methods ✓
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
- List concatenation (`a + b`) ✓
- Dict merge (`d1 | d2`) ✓
- Method chaining (return self) ✓
- Conditional expressions (ternary) ✓
- getattr/hasattr/setattr ✓
- Chained string methods ✓
- List slicing with step, negative indexing ✓
- String multiplication ✓
- `in` operator on lists ✓
