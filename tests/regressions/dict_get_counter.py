# Regression: dict.get() counter pattern
# d[k] = d.get(k, 0) + 1 should produce int values, not float.
# The UNKNOWN VKind from dict.get() caused the binop to unconditionally
# promote to double, making the stored value float.

# Basic counter pattern
d = {}
for c in "abracadabra":
    d[c] = d.get(c, 0) + 1
print(d["a"])  # 5
print(d["b"])  # 2
print(d["r"])  # 2

# Verify values are ints, not floats
val = d.get("a", 0)
x = val + 1
print(x)       # 6 (not 6.0)

# Subtraction
y = val - 2
print(y)       # 3 (not 3.0)

# Multiplication
z = val * 3
print(z)       # 15 (not 15.0)

# Floor division
w = val // 2
print(w)       # 2 (not 2.0)

# Modulo
m = val % 3
print(m)       # 2 (not 2.0)

# Chained operations
result = d.get("a", 0) + d.get("b", 0)
print(result)  # 7 (not 7.0)
