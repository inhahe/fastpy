# Adapted from CPython Lib/test/test_range.py
# Tests range() operations

# Basic range
print(list(range(5)))
print(list(range(0)))
print(list(range(1)))
print(list(range(10)))

# Start, stop
print(list(range(2, 7)))
print(list(range(0, 5)))
print(list(range(-3, 3)))
print(list(range(5, 5)))
print(list(range(5, 3)))

# Start, stop, step
print(list(range(0, 10, 2)))
print(list(range(1, 10, 2)))
print(list(range(0, 20, 5)))
print(list(range(10, 0, -1)))
print(list(range(10, 0, -2)))
print(list(range(5, -5, -3)))

# Length
print(len(range(10)))
print(len(range(0)))
print(len(range(5, 15)))
print(len(range(0, 10, 3)))
print(len(range(10, 0, -1)))

# in operator
print(5 in range(10))
print(10 in range(10))
print(-1 in range(10))
print(5 in range(0, 10, 2))
print(5 in range(1, 10, 2))
print(0 in range(0))

# Indexing
r = range(10)
print(r[0])
print(r[5])
print(r[9])
print(r[-1])
print(r[-2])

# Slicing (produces range)
r2 = range(20)
print(list(r2[2:8]))
print(list(r2[::3]))
print(list(r2[15:5:-2]))

# Iteration
total = 0
for i in range(1, 11):
    total = total + i
print(total)

# Nested range
matrix = []
for i in range(3):
    row = []
    for j in range(3):
        row.append(i * 3 + j)
    matrix.append(row)
print(matrix)

# Range with enumerate
pairs = []
for idx, val in enumerate(range(5, 10)):
    pairs.append((idx, val))
print(pairs)

# Range equality
print(range(10) == range(10))
print(range(0, 10, 1) == range(10))
print(range(10) == range(11))
print(range(0, 10, 2) == range(0, 10, 2))

# Count and index
print(range(10).count(5))
print(range(10).count(10))
print(range(10).index(5))
print(range(0, 20, 3).index(9))

# Reversed
print(list(reversed(range(5))))
print(list(reversed(range(0, 10, 2))))
print(list(reversed(range(10, 0, -1))))

# Range in list comprehension
squares = [x * x for x in range(10)]
print(squares)

# Bool
print(bool(range(0)))
print(bool(range(1)))
print(bool(range(5, 5)))
