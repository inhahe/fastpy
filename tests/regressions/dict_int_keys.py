# Regression: dict with int keys (common in dict comprehensions).
# Before fix: Dict access with non-string key not supported.
# Fix: codegen converts int keys to strings internally at set/get time.

# Dict comprehension with int keys
squares = {i: i*i for i in range(5)}
for k in range(5):
    print(k, squares[k])

# Dict literal with int keys
d = {1: "one", 2: "two", 3: "three"}
print(d[1])
print(d[2])
print(d[3])

# Set int key via subscript
counts = {}
for i in range(3):
    counts[i] = i * 10
for k in range(3):
    print(k, counts[k])

# Check `in` with int key works via converted string
print(1 in d)
print(99 in d)
