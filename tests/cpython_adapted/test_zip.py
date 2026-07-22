# Adapted from CPython Lib/test/test_zip.py (and related)
# Tests zip() operations

# Basic zip
for a, b in zip([1, 2, 3], ["a", "b", "c"]):
    print(a, b)

# Convert to list
print(list(zip([1, 2, 3], [4, 5, 6])))
print(list(zip(["x", "y"], [10, 20])))

# Unequal lengths (truncates to shortest)
print(list(zip([1, 2, 3], [4, 5])))
print(list(zip([1], [4, 5, 6])))

# Empty
print(list(zip([], [])))
print(list(zip([1, 2], [])))
print(list(zip([], [1, 2])))

# Three iterables
result = list(zip([1, 2, 3], ["a", "b", "c"], [10, 20, 30]))
print(result)

# Zip with range
print(list(zip(range(5), range(5, 10))))

# Unzip pattern (transpose)
pairs = [(1, "a"), (2, "b"), (3, "c")]
nums = []
chars = []
for n, c in pairs:
    nums.append(n)
    chars.append(c)
print(nums)
print(chars)

# Zip for parallel iteration
names = ["Alice", "Bob", "Charlie"]
scores = [95, 87, 92]
for name, score in zip(names, scores):
    print(name, score)

# Zip with enumerate
for i, (a, b) in enumerate(zip([10, 20, 30], [1, 2, 3])):
    print(i, a, b)

# Zip to create dict
keys = ["a", "b", "c"]
values = [1, 2, 3]
d = {}
for k, v in zip(keys, values):
    d[k] = v
print(sorted(d.items()))

# Single iterable
print(list(zip([1, 2, 3])))

# Zip strings
for a, b in zip("abc", "xyz"):
    print(a, b)

# Dot product pattern
v1 = [1, 2, 3]
v2 = [4, 5, 6]
dot = 0
for a, b in zip(v1, v2):
    dot = dot + a * b
print(dot)
