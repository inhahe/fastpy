# Adapted from CPython Lib/test/test_bool.py
# Tests boolean operations

# Basic values
print(True)
print(False)
print(type(True) == type(False))

# Logical operators
print(True and True)
print(True and False)
print(False and True)
print(False and False)
print(True or True)
print(True or False)
print(False or True)
print(False or False)
print(not True)
print(not False)

# Short-circuit evaluation
def side_effect(x):
    print("evaluated", x)
    return x

print(True or side_effect(42))
print(False and side_effect(42))
print(False or side_effect(99))
print(True and side_effect(77))

# Truthiness
print(bool(0))
print(bool(1))
print(bool(-1))
print(bool(0.0))
print(bool(3.14))
print(bool(""))
print(bool("hello"))
print(bool([]))
print(bool([1]))
print(bool({}))
print(bool({"a": 1}))
print(bool(None))

# Comparisons return bool
print(3 < 5)
print(3 > 5)
print(3 == 3)
print(3 != 3)
print(type(3 < 5) == type(True))

# Bool as int
print(True + True)
print(True + 1)
print(False + 0)
print(True * 10)
print(False * 10)
print(int(True))
print(int(False))

# Bool in conditions
if True:
    print("yes")
if not False:
    print("also yes")
if 1:
    print("truthy int")
if "x":
    print("truthy str")
if not 0:
    print("falsy int")
if not "":
    print("falsy str")
if not None:
    print("falsy None")

# Bool with containers
lst = [True, False, True, True, False]
print(sum(1 for x in lst if x))
print(sum(1 for x in lst if not x))

# Any/all patterns
def all_true(items):
    for item in items:
        if not item:
            return False
    return True

def any_true(items):
    for item in items:
        if item:
            return True
    return False

print(all_true([True, True, True]))
print(all_true([True, False, True]))
print(any_true([False, False, True]))
print(any_true([False, False, False]))

# Identity
print(True is True)
print(False is False)
print(True is not False)
