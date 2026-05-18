# Adapted from CPython Lib/test/test_compare.py
# Tests comparison operators and chaining

# Integer comparisons
print(1 < 2)
print(2 < 1)
print(1 <= 1)
print(1 >= 1)
print(1 == 1)
print(1 != 2)
print(1 != 1)

# Float comparisons
print(1.5 < 2.5)
print(2.5 < 1.5)
print(1.5 == 1.5)
print(1.5 != 2.5)

# Mixed int/float
print(1 < 1.5)
print(2 > 1.5)
print(1 == 1.0)
print(1 != 1.0)

# String comparisons
print("abc" < "abd")
print("abc" == "abc")
print("abc" != "abd")
print("abc" < "abcd")
print("" < "a")
print("z" > "a")
print("hello" == "hello")
print("hello" != "world")

# List comparisons
print([1, 2, 3] == [1, 2, 3])
print([1, 2, 3] != [1, 2, 4])
print([1, 2] < [1, 3])
print([1, 2, 3] < [1, 2, 3, 4])
print([1, 2, 4] > [1, 2, 3])
print([] < [1])
print([] == [])

# Tuple comparisons
print((1, 2, 3) == (1, 2, 3))
print((1, 2) < (1, 3))
print((1, 2, 3) < (1, 2, 3, 4))
print(() < (1,))
print(() == ())

# Chained comparisons
x = 5
print(1 < x < 10)
print(1 < x < 3)
print(0 <= x <= 10)
print(5 <= x <= 5)
print(1 < 2 < 3 < 4 < 5)
print(1 < 2 < 3 < 2 < 5)

# Chained with variables
a, b, c = 1, 2, 3
print(a < b < c)
print(a < b > c)
print(a <= b <= c)
print(a == a < b)

# is / is not
print(None is None)
print(1 is not None)
print(None is not None)

# is with small integers (implementation detail but consistent)
a = 1
b = 1
print(a is b)

# Comparison with None
print(None == None)
print(None is None)
print(1 != None)

# Boolean comparisons
print(True == True)
print(True == False)
print(True > False)
print(False < True)
print(True == 1)
print(False == 0)

# in / not in
print(3 in [1, 2, 3, 4, 5])
print(6 in [1, 2, 3, 4, 5])
print(6 not in [1, 2, 3, 4, 5])
print("a" in "abc")
print("z" in "abc")
print("ab" in "abc")
print("key" in {"key": 1, "other": 2})
print("missing" in {"key": 1})

# Comparison in expressions
nums = [3, 1, 4, 1, 5, 9, 2, 6]
above_4 = [x for x in nums if x > 4]
print(above_4)

# Min/max use comparisons
print(min(3, 1, 4, 1, 5))
print(max(3, 1, 4, 1, 5))
print(min("apple", "banana", "cherry"))
print(max("apple", "banana", "cherry"))
