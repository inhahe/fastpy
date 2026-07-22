# Regression: callable() and type().__name__ for functions/classes
#
# Bug 1: callable(f) returned False for user-defined functions because
# the function pointer was stored as a raw i64 with INT tag, so the
# CPython bridge saw it as a Python int (not callable).
# Fix: Added native callable() handler that checks _user_functions,
# _user_classes, _lambda_names, and _func_aliases.
#
# Bug 2: type(f).__name__ returned "int" for functions (same tag issue).
# Fix: Added check for functions/aliases in type(x).__name__ resolution.
#
# Bug 3: type(MyClass).__name__ returned "MyClass" instead of "type".
# Fix: Changed the user_classes branch to return "type" (or metaclass).

# 1. callable() on functions
def f(x):
    return x * 2
assert callable(f) == True

# 2. callable() on function alias
fn = f
assert callable(fn) == True

# 3. callable() on class
class Foo:
    pass
assert callable(Foo) == True

# 4. callable() on lambda
g = lambda x: x + 1
assert callable(g) == True

# 5. callable() on non-callables
assert callable(42) == False
assert callable("hello") == False
assert callable([1, 2]) == False
assert callable(None) == False

# 6. type(f).__name__ for function
assert type(f).__name__ == "function"

# 7. type(fn).__name__ for function alias
assert type(fn).__name__ == "function"

# 8. type(Foo).__name__ for class
assert type(Foo).__name__ == "type"

# 9. type(instance).__name__ for class instance
foo = Foo()
assert type(foo).__name__ == "Foo"

# 10. type(lambda).__name__
assert type(g).__name__ == "function"

# 11. callable on instance with __call__
class Adder:
    def __init__(self, n):
        self.n = n
    def __call__(self, x):
        return x + self.n

a = Adder(5)
assert callable(a) == True
assert a(10) == 15

print("ok")
