# Regression: method coverage expansion
# Tests int/float methods, new str methods, set methods, dict methods.

# === int methods ===
print((0).bit_length())      # 0
print((1).bit_length())      # 1
print((42).bit_length())     # 6
print((255).bit_length())    # 8
print((-1).bit_length())     # 1
print((-42).bit_length())    # 6
print((42).bit_count())      # 3
print((0).bit_count())       # 0
print((255).bit_count())     # 8

# === float methods ===
print((3.0).is_integer())    # True
print((3.5).is_integer())    # False
print((-2.0).is_integer())   # True
print((0.0).is_integer())    # True

# === str methods ===
print("a.b.c".rsplit(".", 1))         # ['a.b', 'c']
print("hello".rsplit(".", 1))         # ['hello']
print("a.b.c".rsplit("."))            # ['a', 'b', 'c']
print("Hello World".istitle())        # True
print("hello world".istitle())        # False
print("hello".isidentifier())         # True
print("123abc".isidentifier())        # False
print("hello".isprintable())          # True
print("123".isdecimal())              # True
print("abc".isdecimal())              # False
print("123".isnumeric())              # True
print("Hello".casefold())             # hello

# === set methods ===
s = {1, 2, 3}
t = {2, 3, 4}
print(s.union(t))                     # {1, 2, 3, 4}
print(s.intersection(t))              # {2, 3}
print(s.difference(t))                # {1}
print(s.issubset({1, 2, 3, 4}))      # True
print(s.issuperset({1, 2}))           # True
print(s.isdisjoint({4, 5}))           # True

# === dict methods ===
d = {"a": 1, "b": 2, "c": 3}
item = d.popitem()
print(item)                           # ('c', 3)
print(d)                              # {'a': 1, 'b': 2}
d2 = d.copy()
d2["x"] = 99
print(d)                              # {'a': 1, 'b': 2}
print(d2)                             # {'a': 1, 'b': 2, 'x': 99}
print(d.pop("a", 0))                  # 1
print(d.pop("z", 0))                  # 0
