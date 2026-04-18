# Regression: int(str) and float(str) now raise ValueError on invalid
# input, matching CPython. Before fix, strtoll/strtod silently returned 0.

try:
    x = int("abc")
except ValueError as e:
    print("int1:", e)

try:
    x = int("")
except ValueError as e:
    print("int2:", e)

try:
    x = int("12abc")
except ValueError as e:
    print("int3:", e)

# Valid ones still work
print(int("42"))
print(int("  42  "))
print(int("-42"))

try:
    x = float("xyz")
except ValueError as e:
    print("float1:", e)

print(float("3.14"))
print(float("  2.5  "))
