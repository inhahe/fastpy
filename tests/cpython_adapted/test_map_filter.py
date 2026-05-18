# Adapted from CPython Lib/test/test_builtin.py (map/filter sections)
# Tests map() and filter() operations

# Basic map
print(list(map(abs, [-1, -2, 3, -4, 5])))
print(list(map(len, ["hello", "hi", "world"])))

# Map with lambda
print(list(map(lambda x: x * 2, [1, 2, 3, 4, 5])))
print(list(map(lambda x: x * x, range(6))))

# Map with named function
def double(x):
    return x * 2

print(list(map(double, [1, 2, 3, 4, 5])))

def add_one(x):
    return x + 1

print(list(map(add_one, [10, 20, 30])))

# Map empty
print(list(map(abs, [])))

# Map with two args
def add(a, b):
    return a + b

print(list(map(add, [1, 2, 3], [10, 20, 30])))

# Basic filter
print(list(filter(lambda x: x > 0, [-2, -1, 0, 1, 2])))
print(list(filter(lambda x: x % 2 == 0, range(10))))

# Filter with named function
def is_positive(x):
    return x > 0

print(list(filter(is_positive, [-3, -1, 0, 2, 5])))

def is_even(x):
    return x % 2 == 0

print(list(filter(is_even, range(10))))

# Filter with None (truthy)
print(list(filter(None, [0, 1, "", "a", None, True, False, [], [1]])))

# Filter empty
print(list(filter(lambda x: x > 0, [])))

# Filter all pass
print(list(filter(lambda x: True, [1, 2, 3])))

# Filter none pass
print(list(filter(lambda x: False, [1, 2, 3])))

# Chained map and filter
nums = range(20)
# Get squares of even numbers
result = list(map(lambda x: x * x, filter(lambda x: x % 2 == 0, nums)))
print(result)

# Filter strings
words = ["hello", "hi", "", "world", "", "python"]
print(list(filter(len, words)))
print(list(filter(lambda w: len(w) > 3, words)))

# Map for type conversion
str_nums = ["1", "2", "3", "4", "5"]
print(list(map(int, str_nums)))

# Sum with map
vals = [1, 2, 3, 4, 5]
print(sum(map(lambda x: x * x, vals)))

# Count with filter
data = [1, -2, 3, -4, 5, -6, 7, -8, 9, -10]
positives = list(filter(lambda x: x > 0, data))
print(len(positives))
print(positives)
