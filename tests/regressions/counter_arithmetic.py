# Regression: Counter arithmetic and missing-key access
# Counter[missing_key] should return 0 (not raise KeyError)
# Counter arithmetic (+, -, |, &) should produce Counter results

from collections import Counter

# Basic Counter operations
c1 = Counter(["a", "b", "a", "b", "a"])
c2 = Counter(["b", "c", "b"])
print(c1["a"])   # 3
print(c1["b"])   # 2
print(c1["z"])   # 0 (missing key)

# Addition
c3 = c1 + c2
print(c3["a"])   # 3
print(c3["b"])   # 4
print(c3["c"])   # 1

# Subtraction (only positive counts)
c4 = c1 - c2
print(c4["a"])   # 3
print(c4["b"])   # 0 (2-2=0, dropped)

# Union (max)
c5 = c1 | c2
print(c5["a"])   # 3
print(c5["b"])   # 2

# Intersection (min)
c6 = c1 & c2
print(c6["b"])   # 2

# Kwargs constructor
c7 = Counter(x=5, y=3, z=1)
print(c7["x"])   # 5
print(c7["y"])   # 3
print(c7["w"])   # 0 (missing)

# Chained arithmetic
c8 = (c1 + c2) - c2
print(c8["a"])   # 3
print(c8["b"])   # 2
