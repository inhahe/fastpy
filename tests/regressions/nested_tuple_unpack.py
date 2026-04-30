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

# Deep nesting — 3 levels (P1-A fix)
(x, (y, (z, w))) = (10, (20, (30, 40)))
print(x, y, z, w)

# For-loop with nested tuple target (P1-B fix)
data = [((1, 2), 3), ((4, 5), 6)]
for (a, b), c in data:
    print(a, b, c)

# For-loop with 3-level nested tuple target
data2 = [((1, (2, 3)), 4), ((5, (6, 7)), 8)]
for (a, (b, c)), d in data2:
    print(a, b, c, d)
