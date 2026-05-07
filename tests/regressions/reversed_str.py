# reversed() on strings should produce a list of characters in reverse order

# Basic string reversal
r = list(reversed("abc"))
assert r == ["c", "b", "a"], f"got {r}"
print("basic reversed ok")

# Single char
r = list(reversed("x"))
assert r == ["x"]
print("single char ok")

# Empty string
r = list(reversed(""))
assert r == []
print("empty string ok")

# Join reversed
s = "".join(reversed("hello"))
assert s == "olleh", f"got {s}"
print("join reversed ok")

# reversed on list still works
r = list(reversed([1, 2, 3]))
assert r == [3, 2, 1]
print("list reversed ok")
