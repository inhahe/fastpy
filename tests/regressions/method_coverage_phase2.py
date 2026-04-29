# Comprehensive regression tests for method coverage expansion phase 2
# Tests all new features added in this batch

# === str.find with start/end ===
s = "hello world hello"
print(s.find("hello"))           # 0
print(s.find("hello", 1))        # 12
print(s.find("hello", 1, 10))    # -1
print(s.find("world", 0, 11))    # 6

# === str.rfind with start/end ===
print(s.rfind("hello"))           # 12
print(s.rfind("hello", 0, 10))    # 0
print(s.rfind("hello", 1, 10))    # -1

# === str.count with start/end ===
print(s.count("hello"))           # 2
print(s.count("hello", 1))        # 1
print(s.count("hello", 1, 10))    # 0

# === str.index with start/end ===
print(s.index("hello"))           # 0
print(s.index("hello", 1))        # 12

# === str.rindex with start/end ===
print(s.rindex("hello"))          # 12
print(s.rindex("hello", 0, 10))   # 0

# === str.startswith with start/end ===
print(s.startswith("world", 6))        # True
print(s.startswith("world", 6, 11))    # True
print(s.startswith("world", 6, 8))     # False

# === str.endswith with start/end ===
print(s.endswith("hello"))             # True
print(s.endswith("world", 0, 11))      # True

# === str.startswith/endswith with tuple ===
print("hello".startswith(("he", "wo")))  # True
print("world".startswith(("he", "wo")))  # True
print("other".startswith(("he", "wo")))  # False
print("hello".endswith(("lo", "ld")))    # True
print("world".endswith(("lo", "ld")))    # True
print("other".endswith(("lo", "ld")))    # False

# === str.lstrip/rstrip with chars ===
print("xxhelloxx".lstrip("x"))    # helloxx
print("xxhelloxx".rstrip("x"))    # xxhello
print("aabcba".lstrip("ab"))      # cba
print("aabcba".rstrip("ab"))      # aabc

# === list.index with start/stop ===
lst = [10, 20, 30, 20, 40]
print(lst.index(20))          # 1
print(lst.index(20, 2))       # 3
print(lst.index(20, 2, 4))    # 3

# === list.index with string values ===
names = ["apple", "banana", "cherry"]
print(names.index("banana"))   # 1
print(names.index("cherry"))   # 2

# === list.count with string values ===
words = ["hello", "world", "hello", "foo"]
print(words.count("hello"))    # 2
print(words.count("foo"))      # 1
print(words.count("bar"))      # 0

# === bytes.decode ===
b = b"hello"
print(b.decode())  # hello

# === dict.fromkeys ===
keys = ["a", "b", "c"]
d = dict.fromkeys(keys)
print(d["a"])       # None
d2 = dict.fromkeys(keys, 0)
print(d2["a"])      # 0
print(d2["c"])      # 0

# === dict.clear ===
d3 = {"x": 1, "y": 2}
d3.clear()
print(len(d3))      # 0

# === float.as_integer_ratio ===
print((0.5).as_integer_ratio())    # (1, 2)
print((1.5).as_integer_ratio())    # (3, 2)
print((0.0).as_integer_ratio())    # (0, 1)
print((-0.5).as_integer_ratio())   # (-1, 2)

# === int.to_bytes ===
b3 = (255).to_bytes(1, "big")
print(len(b3))      # 1

# === int.from_bytes ===
val = int.from_bytes(b"\x04\x01", "big")
print(val)           # 1025

# === str.maketrans and str.translate ===
table = str.maketrans("aeiou", "12345")
print("hello world".translate(table))  # h2ll4 w4rld
print("xyz".translate(table))          # xyz (no change)

# === list.count with string values ===
words = ["hello", "world", "hello", "foo"]
print(words.count("hello"))    # 2
print(words.count("bar"))      # 0
