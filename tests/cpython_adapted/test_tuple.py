# Adapted from CPython Lib/test/test_tuple.py
# Tests tuple operations

# Basic construction
t = (1, 2, 3, 4, 5)
print(t)
print(len(t))

# Indexing
print(t[0])
print(t[-1])
print(t[2])

# Slicing
print(t[1:3])
print(t[:2])
print(t[3:])
print(t[::2])
print(t[::-1])

# Unpacking
a, b, c = (10, 20, 30)
print(a, b, c)

x, y = (1, 2)
print(x, y)

# Concatenation
print((1, 2) + (3, 4))
print(() + (1,))
print((1,) + ())

# Multiplication
print((1, 2) * 3)
print((0,) * 5)
print((1, 2, 3) * 0)

# Comparison
print((1, 2, 3) == (1, 2, 3))
print((1, 2, 3) == (1, 2, 4))
print((1, 2) < (1, 3))
print((1, 2, 3) < (1, 2, 3, 4))
print((1, 2, 4) > (1, 2, 3))
print(() < (1,))

# in operator
print(3 in (1, 2, 3, 4, 5))
print(6 in (1, 2, 3, 4, 5))
print(3 not in (1, 2, 3, 4, 5))

# Count and index
t2 = (1, 2, 3, 2, 1, 2, 3)
print(t2.count(2))
print(t2.count(5))
print(t2.index(3))
print(t2.index(2))

# Nested tuples
nested = ((1, 2), (3, 4), (5, 6))
print(nested[1])
print(nested[0][1])

# Single element tuple
single = (42,)
print(single)
print(len(single))
print(single[0])

# Empty tuple
empty = ()
print(empty)
print(len(empty))

# Tuple as dict key
d = {(1, 2): "a", (3, 4): "b"}
print(d[(1, 2)])
print(d[(3, 4)])

# Iteration
total = 0
for x in (10, 20, 30, 40):
    total = total + x
print(total)

# Multiple assignment swap
a = 1
b = 2
a, b = b, a
print(a, b)

# Tuple in list comprehension
pairs = [(x, x * x) for x in range(5)]
print(pairs)

# Bool of tuple
print(bool(()))
print(bool((1,)))
print(bool((0,)))
