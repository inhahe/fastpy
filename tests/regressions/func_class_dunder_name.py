# Regression: func.__name__ and Class.__name__ attribute access
# Bug: accessing __name__ on functions or classes crashed because:
# 1. Functions (VKind.CLOSURE) are not FpyObj instances, so obj_get_fv
#    segfaulted when dereferencing a closure pointer as an object.
# 2. Classes took the class-level constant access path which returned
#    ir.Constant(i64, 0) for unknown attrs including __name__.
# Fix: added compile-time __name__/__qualname__ resolution in
# _emit_attr_load, _load_or_wrap_fv, and class constant access paths.

def greet():
    print("hello")

def add(a, b):
    return a + b

class MyClass:
    def method(self):
        return 1

class Animal:
    def __init__(self, name):
        self.name = name

# Case 1: function __name__
print(greet.__name__)
print(add.__name__)

# Case 2: class __name__
print(MyClass.__name__)
print(Animal.__name__)

# Case 3: assignment to variable
name = greet.__name__
print(name)

# Case 4: in list
names = [greet.__name__, add.__name__]
print(names)

# Case 5: iterate list of __name__
for n in names:
    print(n)

# Case 6: comparison
if greet.__name__ == "greet":
    print("match")
else:
    print("no match")

# Case 7: string operations
print(greet.__name__.upper())
print(len(MyClass.__name__))

# Case 8: concatenation
print("Function: " + greet.__name__)
