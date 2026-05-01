# Regression: tuple unpacking into subscript and attribute targets (P1-A fix)
# Previously, subscript/attribute targets in general unpacking (Path 3) silently
# no-oped — the assignment was skipped entirely.

# --- Subscript targets ---

# 1. Dict subscript from direct tuple unpack
d = {"a": 0, "b": 0}
d["a"], d["b"] = 10, 20
print(d["a"], d["b"])

# 2. List subscript from direct tuple unpack
lst = [0, 0, 0]
lst[0], lst[1] = 5, 6
print(lst[0], lst[1])

# --- Attribute targets ---

# 3. Attribute store from direct tuple unpack
class Point:
    def __init__(self):
        self.x = 0
        self.y = 0

p = Point()
p.x, p.y = 3, 4
print(p.x, p.y)

# 4. Mixed: name + subscript in direct unpack
result = [0]
a, result[0] = 1, 2
print(a, result[0])

# 5. Mixed: name + attribute in direct unpack
class Box:
    def __init__(self):
        self.val = 0

b = Box()
c, b.val = 7, 8
print(c, b.val)
