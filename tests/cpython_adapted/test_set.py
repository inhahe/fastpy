# Adapted from CPython Lib/test/test_set.py
# Tests set operations

# Basic construction
s = {1, 2, 3, 4, 5}
print(sorted(s))
print(len(s))

# Add/discard/remove
s.add(6)
print(sorted(s))
s.discard(3)
print(sorted(s))
s.discard(99)  # no error
print(sorted(s))

# in operator
print(1 in s)
print(99 in s)
print(99 not in s)

# Set from list (dedup)
dups = [1, 2, 2, 3, 3, 3, 4, 4, 4, 4]
print(sorted(set(dups)))

# Union
a = {1, 2, 3}
b = {3, 4, 5}
print(sorted(a | b))
print(sorted(a.union(b)))

# Intersection
print(sorted(a & b))
print(sorted(a.intersection(b)))

# Difference
print(sorted(a - b))
print(sorted(a.difference(b)))
print(sorted(b - a))

# Symmetric difference
print(sorted(a ^ b))
print(sorted(a.symmetric_difference(b)))

# Subset/superset
print({1, 2} <= {1, 2, 3})
print({1, 2, 3} <= {1, 2, 3})
print({1, 2, 3, 4} <= {1, 2, 3})
print({1, 2, 3} >= {1, 2})
print({1, 2, 3} >= {1, 2, 3})

# issubset/issuperset
print({1, 2}.issubset({1, 2, 3}))
print({1, 2, 3}.issuperset({1, 2}))

# isdisjoint
print({1, 2}.isdisjoint({3, 4}))
print({1, 2}.isdisjoint({2, 3}))

# Copy
c = {1, 2, 3}
d = c.copy()
d.add(4)
print(sorted(c))
print(sorted(d))

# Clear
e = {1, 2, 3}
e.clear()
print(sorted(e))
print(len(e))

# Pop (non-deterministic, just check length)
f = {10, 20, 30}
f.pop()
print(len(f))

# Iteration
g = {5, 3, 1, 4, 2}
result = []
for x in g:
    result.append(x)
print(sorted(result))

# Set comprehension
evens = {x for x in range(10) if x % 2 == 0}
print(sorted(evens))

# Update (in-place union)
h = {1, 2, 3}
h.update({4, 5})
print(sorted(h))

# Intersection update
i = {1, 2, 3, 4, 5}
i.intersection_update({2, 4, 6})
print(sorted(i))

# Difference update
j = {1, 2, 3, 4, 5}
j.difference_update({2, 4})
print(sorted(j))

# Empty set
empty = set()
print(len(empty))
print(sorted(empty))

# Bool of set
print(bool(set()))
print(bool({1}))

# Equality
print({1, 2, 3} == {3, 2, 1})
print({1, 2, 3} == {1, 2, 4})
print(set() == set())
