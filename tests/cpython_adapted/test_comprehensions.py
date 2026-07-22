# Adapted from CPython Lib/test/test_listcomps.py and test_genexps.py
# Tests list/dict/set comprehensions and generator expressions

# Basic list comprehension
print([x for x in range(10)])
print([x * 2 for x in range(5)])
print([x * x for x in range(8)])

# With filter
print([x for x in range(20) if x % 3 == 0])
print([x for x in range(20) if x % 2 == 0 and x % 3 == 0])

# Nested comprehension
print([x + y for x in range(3) for y in range(3)])
print([(x, y) for x in range(3) for y in range(3) if x != y])

# String comprehension
print([c.upper() for c in "hello"])
print([c for c in "hello world" if c != " "])

# Comprehension with function call
def square(x):
    return x * x

print([square(x) for x in range(6)])

# Nested list flatten
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
flat = [x for row in matrix for x in row]
print(flat)

# Comprehension with conditional expression
print([x if x % 2 == 0 else -x for x in range(10)])

# Dict comprehension
print(sorted({x: x * x for x in range(6)}.items()))
print(sorted({k: v for k, v in [("a", 1), ("b", 2), ("c", 3)]}.items()))

# Dict comprehension with filter
print(sorted({x: x * x for x in range(10) if x % 2 == 0}.items()))

# Set comprehension
print(sorted({x % 5 for x in range(20)}))
print(sorted({len(w) for w in ["hello", "hi", "hey", "world", "wow"]}))

# Generator expression with sum
print(sum(x * x for x in range(10)))
print(sum(x for x in range(100) if x % 2 == 0))

# Generator expression with min/max
print(min(x * x for x in range(-5, 6)))
print(max(x * x for x in range(-5, 6)))

# Generator expression with list
print(list(x * 3 for x in range(5)))
print(list(x for x in range(20) if x % 7 == 0))

# Comprehension building strings
words = ["hello", "world", "python", "code"]
print([w.upper() for w in words])
print([w[0] for w in words])
lengths = [len(w) for w in words]
print(lengths)

# Multiple comprehensions
a = [x for x in range(5)]
b = [x * 2 for x in a]
c = [x + 1 for x in b]
print(c)

# Comprehension with enumerate
print([(i, x) for i, x in enumerate(["a", "b", "c"])])

# Comprehension with zip
keys = ["x", "y", "z"]
vals = [1, 2, 3]
print(sorted({k: v for k, v in zip(keys, vals)}.items()))

# Nested list via comprehension
print([[i * j for j in range(1, 4)] for i in range(1, 4)])

# Filter and transform
numbers = [1, -2, 3, -4, 5, -6, 7, -8, 9, -10]
print([abs(x) for x in numbers])
print([x for x in numbers if x > 0])
print(sum(x for x in numbers if x > 0))
