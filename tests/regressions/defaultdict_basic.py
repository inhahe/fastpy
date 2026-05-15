# Regression: collections.defaultdict basic operations

from collections import defaultdict

# defaultdict(list): append single item
d = defaultdict(list)
d["a"].append(1)
print(d["a"])           # [1]

# Append multiple items
d["a"].append(2)
d["a"].append(3)
print(d["a"])           # [1, 2, 3]

# New key auto-creates empty list
d["b"].append(99)
print(d["b"])           # [99]

# defaultdict(int): increment
d2 = defaultdict(int)
d2["x"] += 1
d2["x"] += 1
d2["y"] += 5
print(d2["x"])          # 2
print(d2["y"])          # 5

# Access missing key returns default without setting error
d3 = defaultdict(int)
print(d3["missing"])    # 0
