# Regression: type(x) == int / type(x) is str patterns
# Previously returned False for all type comparisons because
# type() returned a CPython type object that didn't compare
# equal to the builtin type name. Now folded at compile time.

x = 42
print(type(x) == int)     # True
print(type(x) == str)     # False
print(type(x) != int)     # False
print(type(x) is int)     # True
print(type(x) is not int) # False

y = "hello"
print(type(y) == str)     # True
print(type(y) == int)     # False

z = 3.14
print(type(z) == float)   # True

b = True
print(type(b) == bool)    # True

lst = [1, 2, 3]
print(type(lst) == list)  # True

d = {"a": 1}
print(type(d) == dict)    # True

# Inside function (FV-backed variables)
def check_types():
    a = 100
    print(type(a) == int)   # True
    s = "world"
    print(type(s) == str)   # True
    f = 2.5
    print(type(f) == float) # True

check_types()
