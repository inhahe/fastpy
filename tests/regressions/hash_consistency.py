# hash() must be consistent across types: hash(1) == hash(1.0) in Python

# Same integer
assert hash(42) == hash(42)
print("int hash consistent ok")

# Same string
assert hash("abc") == hash("abc")
print("str hash consistent ok")

# hash(True) == hash(1) in Python
assert hash(True) == hash(1)
print("bool-int hash ok")

# hash(False) == hash(0)
assert hash(False) == hash(0)
print("bool-zero hash ok")

# Different ints → different hashes (generally)
assert hash(1) != hash(2)
print("different ints ok")

# hash of None
h = hash(None)
assert hash(None) == h
print("none hash ok")
