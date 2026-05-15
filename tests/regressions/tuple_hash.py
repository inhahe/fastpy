# Tuple hashing: tuples with different contents must have different hashes,
# and tuples used as dict keys must work correctly.

# Basic: different tuples → different hashes
h1 = hash((1, 2))
h2 = hash((3, 4))
assert h1 != h2, f"hash collision: {h1} == {h2}"
print("different tuples ok")

# Same contents → same hash
h3 = hash((1, 2))
assert h1 == h3, f"same content different hash: {h1} != {h3}"
print("same content ok")

# Tuple as dict key
d = {}
d[(1, 2)] = "a"
d[(3, 4)] = "b"
assert d[(1, 2)] == "a"
assert d[(3, 4)] == "b"
assert len(d) == 2
print("dict key ok")

# Nested tuples
h4 = hash((1, (2, 3)))
h5 = hash((1, (2, 4)))
assert h4 != h5
print("nested tuple hash ok")

# hash() on basic types
assert hash(42) == hash(42)
assert hash("hello") == hash("hello")
assert hash(42) != hash(43)
print("basic hash ok")

# Empty tuple
h6 = hash(())
h7 = hash(())
assert h6 == h7
print("empty tuple ok")
