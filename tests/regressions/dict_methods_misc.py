# Test dict.get() with default, dict.setdefault(), dict.popitem(),
# dict.items() iteration

d = {"a": 1, "b": 2, "c": 3}

# dict.get() with default
print(d.get("a"))           # 1
print(d.get("z"))           # None
print(d.get("z", 99))       # 99
print(d.get("b", 99))       # 2

# dict.setdefault()
d2 = {"x": 10}
print(d2.setdefault("x", 0))   # 10  (key exists, return existing)
print(d2.setdefault("y", 20))  # 20  (key missing, insert and return)
print(d2)                       # {'x': 10, 'y': 20}

# dict.items() iteration
d3 = {"one": 1, "two": 2, "three": 3}
pairs = []
for k, v in d3.items():
    pairs.append((k, v))
pairs.sort()
print(pairs)   # [('one', 1), ('three', 3), ('two', 2)]

# dict.popitem() — removes and returns an arbitrary (key, value) pair
# For determinism, use a single-item dict
d4 = {"only": 42}
item = d4.popitem()
print(item)    # ('only', 42)
print(d4)      # {}

# dict.get on empty dict
empty = {}
print(empty.get("k", "default"))  # default
