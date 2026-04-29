# Regression tests for method coverage expansion phase 2
# Tests: str.find/rfind/count/index/rindex with start/end,
#        str.startswith/endswith with tuple and start/end,
#        list.index with start/stop, bytes.decode, dict.fromkeys

# === str.find with start/end ===
s = "hello world hello"
print(s.find("hello"))        # 0
print(s.find("hello", 1))     # 12
print(s.find("hello", 1, 10)) # -1
print(s.find("world", 0, 11)) # 6

# === str.rfind with start/end ===
print(s.rfind("hello"))        # 12
print(s.rfind("hello", 0, 10)) # 0
print(s.rfind("hello", 1, 10)) # -1

# === str.count with start/end ===
print(s.count("hello"))        # 2
print(s.count("hello", 1))     # 1
print(s.count("hello", 1, 10)) # 0

# === str.index with start/end ===
print(s.index("hello"))        # 0
print(s.index("hello", 1))     # 12

# === str.rindex with start/end ===
print(s.rindex("hello"))        # 12
print(s.rindex("hello", 0, 10)) # 0

# === str.startswith with start/end ===
print(s.startswith("world", 6))     # True
print(s.startswith("world", 6, 11)) # True
print(s.startswith("world", 6, 8))  # False

# === str.endswith with start/end ===
print(s.endswith("hello"))          # True
print(s.endswith("world", 0, 11))   # True
print(s.endswith("world", 0, 8))    # False

# === str.startswith/endswith with tuple ===
print("hello".startswith(("he", "wo")))  # True
print("world".startswith(("he", "wo")))  # True
print("other".startswith(("he", "wo")))  # False
print("hello".endswith(("lo", "ld")))    # True
print("world".endswith(("lo", "ld")))    # True
print("other".endswith(("lo", "ld")))    # False

# === list.index with start/stop ===
lst = [10, 20, 30, 20, 40]
print(lst.index(20))          # 1
print(lst.index(20, 2))       # 3
print(lst.index(20, 2, 4))    # 3

# === bytes.decode ===
b = b"hello"
print(b.decode())  # hello

# === dict.fromkeys ===
keys = ["a", "b", "c"]
d = dict.fromkeys(keys)
print(d["a"])  # None
print(d["b"])  # None

d2 = dict.fromkeys(keys, 0)
print(d2["a"])  # 0
print(d2["b"])  # 0
print(d2["c"])  # 0
