# Test various patterns that might be broken

# 1. Chained string methods
s = "  Hello, World!  "
print(s.strip().lower())
print(s.strip().upper())
print(s.strip().replace("World", "Python"))

# 2. List comprehension with method call
words = ["hello", "world", "python"]
print([w.upper() for w in words])

# 3. Dict comprehension with enumerate
items = ["a", "b", "c"]
d = {i: v for i, v in enumerate(items)}
print(sorted(d.items()))

# 4. Nested list comprehension
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
flat = [x for row in matrix for x in row]
print(flat)

# 5. Multiple return values
def minmax(lst):
    return min(lst), max(lst)

lo, hi = minmax([3, 1, 4, 1, 5, 9])
print(lo, hi)

# 6. Default arguments
def greet(name, greeting="Hello"):
    return greeting + " " + name

print(greet("Alice"))
print(greet("Bob", "Hi"))

# 7. String formatting
name = "World"
print(f"Hello, {name}!")
print("Count: {}".format(42))
print("%.2f" % 3.14159)

# 8. List slicing
lst = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
print(lst[2:5])
print(lst[::2])
print(lst[::-1])

# 9. Dictionary operations
d = {"a": 1, "b": 2, "c": 3}
print(sorted(d.keys()))
print(sorted(d.values()))
print(d.get("x", 0))

# 10. Boolean operations
print(all([True, True, True]))
print(any([False, False, True]))
print(not False)
