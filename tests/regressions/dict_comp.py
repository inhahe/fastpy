# Test dict comprehensions

# From pairs list (tuple unpacking)
pairs = [("a", 1), ("b", 2), ("c", 3)]
d1 = {k: v for k, v in pairs}
print(d1)
# {'a': 1, 'b': 2, 'c': 3}

# Square mapping from range
d2 = {x: x**2 for x in range(5)}
print(d2)
# {0: 0, 1: 1, 2: 4, 3: 9, 4: 16}

# With condition filter
d3 = {x: x**2 for x in range(10) if x % 2 == 0}
print(d3)
# {0: 0, 2: 4, 4: 16, 6: 36, 8: 64}

# From dict.items()
src = {"a": 1, "b": 2, "c": 3}
d4 = {k: v * 2 for k, v in src.items()}
print(sorted(d4.items()))
# [('a', 2), ('b', 4), ('c', 6)]

# Filter on dict items
d5 = {k: v for k, v in src.items() if v > 1}
print(sorted(d5.items()))
# [('b', 2), ('c', 3)]

# Key transform
d6 = {k.upper(): v for k, v in src.items()}
print(sorted(d6.items()))
# [('A', 1), ('B', 2), ('C', 3)]

# String length mapping
words = ["hello", "world", "hi", "python"]
d7 = {w: len(w) for w in words}
print(d7)
# {'hello': 5, 'world': 5, 'hi': 2, 'python': 6}
