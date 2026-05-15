# Test 'in' operator and basic operations on dicts with tuple keys

d = {}
d[(1, 2)] = "a"
d[(3, 4)] = "b"
assert (1, 2) in d
assert (3, 4) in d
assert (5, 6) not in d
print("tuple in dict ok")

# Tuple dict from literal
d2 = {(1, 2): "a", (3, 4): "b"}
assert (1, 2) in d2
assert d2[(1, 2)] == "a"
assert d2[(3, 4)] == "b"
assert len(d2) == 2
print("tuple dict literal ok")

# Read back values
assert d[(1, 2)] == "a"
assert d[(3, 4)] == "b"
assert len(d) == 2
print("len ok")
