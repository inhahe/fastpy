# Adapted from CPython Lib/test/test_format.py
# Tests string formatting operations

# str() conversions
print(str(42))
print(str(-17))
print(str(3.14))
print(str(True))
print(str(False))
print(str(None))
print(str([1, 2, 3]))
print(str((1, 2)))
print(str({"a": 1}))

# String concatenation formatting
name = "World"
print("Hello, " + name + "!")
x = 42
print("x = " + str(x))
pi = 3.14159
print("pi = " + str(pi))

# repr-like output
print(str([1, 2, 3]))
print(str(["hello", "world"]))
print(str({"key": "value"}))

# Numeric formatting via str
print(str(1000000))
print(str(-1000000))
print(str(0))
print(str(0.0))
print(str(1.0))
print(str(-0.5))
print(str(100.0))

# Boolean formatting
print(str(True))
print(str(False))
print(str(1 == 1))
print(str(1 == 2))

# List/tuple formatting
print(str([]))
print(str([1]))
print(str([1, 2, 3]))
print(str(()))
print(str((1,)))
print(str((1, 2, 3)))

# Join-based formatting
parts = ["name", "age", "city"]
print(", ".join(parts))
print(" | ".join(parts))
print("".join(["a", "b", "c"]))

# Number to string
for i in range(10):
    print(str(i), end=" ")
print()

# String multiplication for padding
print("=" * 20)
print("-" * 10)
print("abc" * 3)

# Manual padding
def pad_right(s, width):
    while len(s) < width:
        s = s + " "
    return s

def pad_left(s, width):
    while len(s) < width:
        s = " " + s
    return s

print("[" + pad_right("hi", 10) + "]")
print("[" + pad_left("hi", 10) + "]")

# Table formatting
headers = ["Name", "Age", "City"]
rows = [
    ["Alice", "30", "NYC"],
    ["Bob", "25", "LA"],
    ["Charlie", "35", "Chicago"],
]

# Print header
print(" | ".join(headers))
print("-" * 30)
for row in rows:
    print(" | ".join(row))
