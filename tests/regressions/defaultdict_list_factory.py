# Regression: defaultdict(list) factory support
# Tests that defaultdict with list factory correctly creates native lists,
# and that .append(), len(), and print work on the auto-created values.

from collections import defaultdict

# defaultdict(list): append and print
d = defaultdict(list)
d["x"].append(1)
d["x"].append(2)
d["y"].append(3)
print(d["x"])       # [1, 2]
print(d["y"])       # [3]
print(len(d["x"]))  # 2

# defaultdict(int): still works
d2 = defaultdict(int)
d2["a"] += 1
d2["b"] += 2
print(d2["a"])      # 1
print(d2["b"])      # 2

# defaultdict(list) with variable assignment
d3 = defaultdict(list)
d3["items"].append(10)
d3["items"].append(20)
items = d3["items"]
print(items)        # [10, 20]
print(len(items))   # 2
