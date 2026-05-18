# Adapted from CPython Lib/test/test_slice.py
# Tests slice operations on various sequences

# List slicing
a = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

# Basic slices
print(a[2:5])
print(a[:3])
print(a[7:])
print(a[:])
print(a[0:10])

# Negative indices
print(a[-3:])
print(a[:-3])
print(a[-5:-2])

# Step
print(a[::2])
print(a[1::2])
print(a[::3])
print(a[::-1])
print(a[::-2])
print(a[8:2:-1])
print(a[8:2:-2])

# Empty slices
print(a[5:5])
print(a[5:3])
print(a[5:3:1])

# Out of bounds (no error)
print(a[0:100])
print(a[-100:5])
print(a[100:200])

# String slicing
s = "hello world"
print(s[0:5])
print(s[6:])
print(s[:5])
print(s[::2])
print(s[::-1])
print(s[0:11:3])

# Tuple slicing
t = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
print(t[2:5])
print(t[:3])
print(t[7:])
print(t[::2])
print(t[::-1])

# Slice assignment
b = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
b[2:5] = [20, 30, 40]
print(b)

c = [0, 1, 2, 3, 4, 5]
c[1:4] = [10, 20, 30, 40, 50]  # expand
print(c)

d = [0, 1, 2, 3, 4, 5]
d[1:4] = [10]  # shrink
print(d)

e = [0, 1, 2, 3, 4, 5]
e[2:2] = [99, 98, 97]  # insert
print(e)

f = [0, 1, 2, 3, 4, 5]
f[1:4] = []  # delete
print(f)

# Delete via del
g = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
del g[2:5]
print(g)
del g[::2]
print(g)

# Step slice assignment
h = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
h[::2] = [10, 20, 30, 40, 50]
print(h)

# Nested slicing
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
print(matrix[0:2])
print([row[1:] for row in matrix])

# Slice of empty
print([][0:5])
print(""[0:5])
print(()[0:5])
