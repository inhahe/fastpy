# Adapted from CPython Lib/test/test_enumerate.py
# Tests enumerate() operations

# Basic enumerate
for i, x in enumerate(["a", "b", "c"]):
    print(i, x)

# With start
for i, x in enumerate(["x", "y", "z"], 1):
    print(i, x)

# Empty
for i, x in enumerate([]):
    print(i, x)
print("empty done")

# Convert to list
print(list(enumerate(["a", "b", "c"])))
print(list(enumerate(["x", "y"], 5)))

# With range
result = []
for i, x in enumerate(range(5)):
    result.append((i, x))
print(result)

# Enumerate string
for i, ch in enumerate("hello"):
    print(i, ch)

# Nested enumerate
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
for i, row in enumerate(matrix):
    for j, val in enumerate(row):
        if val == 5:
            print(i, j)

# Enumerate with unpacking in list comprehension
pairs = [(i, x * x) for i, x in enumerate(range(5))]
print(pairs)

# Large start value
for i, x in enumerate(["first", "second"], 100):
    print(i, x)

# Enumerate tuple
for i, x in enumerate((10, 20, 30)):
    print(i, x)

# Using enumerate for index tracking
data = [3, 1, 4, 1, 5, 9]
max_val = data[0]
max_idx = 0
for i, x in enumerate(data):
    if x > max_val:
        max_val = x
        max_idx = i
print(max_idx, max_val)
