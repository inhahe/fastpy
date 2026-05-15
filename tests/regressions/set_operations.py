# Set operations

s1 = {1, 2, 3, 4}
s2 = {3, 4, 5, 6}

# Union
print(sorted(s1 | s2))

# Intersection
print(sorted(s1 & s2))

# Difference
print(sorted(s1 - s2))

# Symmetric difference
print(sorted(s1 ^ s2))

# issubset / issuperset
s3 = {1, 2}
print(s3.issubset(s1))
print(s1.issuperset(s3))
print(s1.issubset(s3))
print(s3.issuperset(s1))

# <= and >= operators (subset/superset)
print(s3 <= s1)
print(s1 >= s3)

# Disjoint
s4 = {7, 8}
print(s1.isdisjoint(s4))
print(s1.isdisjoint(s2))

# Set with empty set
empty = set()
print(sorted(s1 | empty))
print(sorted(s1 & empty))
