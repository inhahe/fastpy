# dict() constructor from list of pairs and zip()

# dict from list of tuples
pairs = [(1, "a"), (2, "b"), (3, "c")]
d = dict(pairs)
assert d[1] == "a"
assert d[2] == "b"
assert d[3] == "c"
assert len(d) == 3
print("dict from pairs ok")

# dict from literal list of tuples
d2 = dict([(10, 20), (30, 40)])
assert d2[10] == 20
assert d2[30] == 40
print("dict from literal pairs ok")

# dict from zip
keys = [1, 2, 3]
vals = ["x", "y", "z"]
d3 = dict(zip(keys, vals))
assert d3[1] == "x"
assert d3[2] == "y"
assert d3[3] == "z"
print("dict from zip ok")
