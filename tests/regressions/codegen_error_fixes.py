# Regression tests for CodeGenError sites converted to proper behavior
# (Previously these raised CodeGenError at compile time for valid Python code)

# 1. bool() with no args should return False
x = bool()
print(x)           # False

# 2. float() with no args should return 0.0
y = float()
print(y)            # 0.0

# 3. dict() with integer keys
d = dict([(1, 'one'), (2, 'two'), (3, 'three')])
print(d[1])         # one
print(d[2])         # two
print(len(d))       # 3

# 4. complex ** with integer exponent
c = (1+2j) ** 2
print(c)            # (-3+4j)

# 5. complex ** with another complex
c2 = (2+0j) ** (0+0j)
print(c2)           # (1+0j)

# 6. Dict comprehension with zip tuple unpacking (string keys preserved)
keys = ["a", "b", "c"]
vals = [10, 20, 30]
d2 = {k: v for k, v in zip(keys, vals)}
print(d2["b"])      # 20
