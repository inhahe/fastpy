# dict.update() with keyword arguments

d = {"a": 1}
d.update(b=2, c=3)
assert d["a"] == 1
assert d["b"] == 2
assert d["c"] == 3
print("kw update ok")

# Mixed: positional + keywords
d2 = {"x": 10}
d2.update({"y": 20}, z=30)
assert d2["x"] == 10
assert d2["y"] == 20
assert d2["z"] == 30
print("mixed update ok")

# Overwrite existing keys
d3 = {"a": 1, "b": 2}
d3.update(a=10, c=30)
assert d3["a"] == 10
assert d3["b"] == 2
assert d3["c"] == 30
print("overwrite ok")
