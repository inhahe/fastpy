# Test: string iteration inside a generator function
# The for-loop is expanded to iter()/next() with try/except StopIteration.
# The yielded values are string characters that must preserve their STR tag
# through the generator state machine (attribute store → attr load → return
# with set_ret_tag).

def chars(s):
    for c in s:
        yield c

# Basic: first character
g = chars("hi")
assert next(g) == "h"
assert next(g) == "i"

# Exhaustion
ok = False
try:
    next(g)
except StopIteration:
    ok = True
assert ok

# Collect all via list()
assert list(chars("abc")) == ["a", "b", "c"]

# Empty string
assert list(chars("")) == []

# Single char
assert list(chars("x")) == ["x"]

# Longer string with spaces
assert list(chars("a b")) == ["a", " ", "b"]

print("ok")
