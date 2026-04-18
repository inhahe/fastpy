# String formatting edge cases

# str/repr
print(str(42))
print(str(3.14))
print(str(True))
print(str(None))
print(str([1, 2, 3]))
print(str({"a": 1}))
print(repr("hello"))
print(repr(42))

# bool to str via concat
print("answer: " + str(42))
print("pi is about " + str(3.14))

# Multiline join
parts = ["line1", "line2", "line3"]
print("\n".join(parts))

# Format with multiple values
print("{} and {}".format("abc", 123))
print("{0} / {1}".format("num", 100))
print("{name}: {val}".format(name="x", val=10))

# Conversion via format()
print(f"{42:.0f}")
print(f"{3.14:.1f}")

# Numeric types
print(1 + True)       # 2
print(1 + False)      # 1
print(3.0 * True)     # 3.0
