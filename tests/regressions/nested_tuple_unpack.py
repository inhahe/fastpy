# Regression: nested tuple unpacking

# Direct tuple-tuple unpack
(a, b), c = (1, 2), 3
print(a, b, c)

# Two nested tuples
(x, y), (z, w) = (10, 20), (30, 40)
print(x, y, z, w)

# Mixed: nested tuple + scalar
(p, q), r, s = (5, 6), 7, 8
print(p, q, r, s)

# Single nesting on right side
a, (b, c) = 1, (2, 3)
print(a, b, c)
