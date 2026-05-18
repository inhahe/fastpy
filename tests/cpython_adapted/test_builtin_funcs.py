# Adapted from CPython Lib/test/test_builtin.py
# Tests builtin functions

# abs
print(abs(0))
print(abs(5))
print(abs(-5))
print(abs(3.14))
print(abs(-3.14))

# min/max
print(min(1, 2, 3))
print(min(3, 2, 1))
print(max(1, 2, 3))
print(max(3, 2, 1))
print(min([5, 2, 8, 1, 9]))
print(max([5, 2, 8, 1, 9]))

# sum
print(sum([1, 2, 3, 4, 5]))
print(sum(range(101)))
print(sum([]))
print(sum([1.5, 2.5, 3.0]))

# len
print(len([]))
print(len([1, 2, 3]))
print(len("hello"))
print(len((1, 2, 3, 4)))
print(len({}))
print(len({"a": 1, "b": 2}))

# sorted
print(sorted([3, 1, 4, 1, 5, 9]))
print(sorted([3, 1, 4], reverse=True))
print(sorted("hello"))
print(sorted([]))

# reversed
print(list(reversed([1, 2, 3, 4, 5])))
print(list(reversed([])))
print(list(reversed([1])))

# enumerate
print(list(enumerate(["a", "b", "c"])))
print(list(enumerate(["x", "y"], 10)))

# zip
print(list(zip([1, 2, 3], ["a", "b", "c"])))
print(list(zip([], [])))

# range
print(list(range(5)))
print(list(range(2, 8)))
print(list(range(0, 10, 3)))

# int/float/str conversions
print(int(3.7))
print(int(-3.7))
print(int("42"))
print(float(5))
print(float("3.14"))
print(str(42))
print(str(3.14))
print(str(True))

# bool
print(bool(0))
print(bool(1))
print(bool(""))
print(bool("x"))
print(bool([]))
print(bool([1]))
print(bool(None))

# isinstance
print(isinstance(42, int))
print(isinstance(3.14, float))
print(isinstance("hi", str))
print(isinstance(True, bool))
print(isinstance(True, int))
print(isinstance([], list))
print(isinstance({}, dict))

# divmod
print(divmod(17, 5))
print(divmod(10, 3))
print(divmod(-7, 2))
print(divmod(7, -2))

# pow
print(pow(2, 10))
print(pow(3, 4))
print(pow(2, 10, 100))

# round
print(round(3.14159, 2))
print(round(2.5))
print(round(3.5))
print(round(4.5))
print(round(-0.5))

# chr/ord
print(chr(65))
print(chr(97))
print(chr(48))
print(ord("A"))
print(ord("a"))
print(ord("0"))

# type (name)
print(type(42).__name__)
print(type(3.14).__name__)
print(type("hi").__name__)
print(type(True).__name__)
print(type(None).__name__)
print(type([]).__name__)
print(type({}).__name__)
