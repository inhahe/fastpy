# Regression: for k, v in d.items() where d has integer keys
# Previously, items() iteration always typed keys as strings,
# causing segfault when the key (actually an int) was used as a pointer.

# 1. Copy int-keyed dict via items()
d = {0: 10, 1: 20}
copy = {}
for k, v in d.items():
    copy[k] = v
print(copy)

# 2. Invert int-keyed dict
inv = {}
for k, v in d.items():
    inv[v] = k
print(inv)

# 3. Access keys from items() as ints (arithmetic)
total = 0
for k, v in d.items():
    total += k + v
print(total)

# 4. Mixed: int keys with string values
names = {1: "alice", 2: "bob"}
for k, v in names.items():
    print(f"{k}: {v}")
