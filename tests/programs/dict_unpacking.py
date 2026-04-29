# Dictionary unpacking, merging, and comprehensions

a = {"x": 1, "y": 2}
b = {"y": 3, "z": 4}

# Unpacking merge (PEP 448)
merged = {**a, **b}
print(sorted(merged.items()))

# Merge with literal keys
c = {**a, "w": 0, **b}
print(sorted(c.items()))

# dict() constructor with unpacking — uses native dict merge
# (dict(a, **b) is equivalent to {**a, **b})
d = {**a, **b}
print(sorted(d.items()))

# Dict comprehension with string keys
squares = {str(i): i * i for i in range(5)}
print(sorted(squares.items()))

# Merging with | operator (Python 3.9+)
m1 = {"a": 1, "b": 2}
m2 = {"b": 3, "c": 4}
m3 = m1 | m2
print(sorted(m3.items()))

# dict.get with default
print(m3.get("b"))
print(m3.get("z", -1))

# dict.pop
popped = m3.pop("c")
print(popped)
print(sorted(m3.items()))

print("tests passed!")
