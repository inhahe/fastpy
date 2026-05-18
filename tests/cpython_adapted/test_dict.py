# Adapted from CPython Lib/test/test_dict.py
# Tests dictionary operations

# Basic construction
d = {"a": 1, "b": 2, "c": 3}
print(sorted(d.keys()))
print(sorted(d.values()))
print(len(d))

# Get/set
d["d"] = 4
print(d["d"])
d["a"] = 10
print(d["a"])

# in operator
print("a" in d)
print("z" in d)
print("z" not in d)

# get with default
print(d.get("a"))
print(d.get("z"))
print(d.get("z", 99))

# pop
e = {"x": 1, "y": 2, "z": 3}
print(e.pop("y"))
print(sorted(e.keys()))
print(e.pop("missing", -1))

# setdefault
f = {"a": 1}
print(f.setdefault("a", 99))
print(f.setdefault("b", 2))
print(sorted(f.items()))

# update
g = {"a": 1, "b": 2}
g.update({"b": 20, "c": 30})
print(sorted(g.items()))

# keys, values, items
h = {"x": 10, "y": 20, "z": 30}
print(sorted(h.keys()))
print(sorted(h.values()))
print(sorted(h.items()))

# Delete
i = {"a": 1, "b": 2, "c": 3}
del i["b"]
print(sorted(i.keys()))
print(len(i))

# Clear
j = {"a": 1, "b": 2}
j.clear()
print(j)
print(len(j))

# Copy
k = {"x": 1, "y": 2}
k2 = k.copy()
k2["z"] = 3
print(sorted(k.keys()))
print(sorted(k2.keys()))

# Iteration
m = {"a": 1, "b": 2, "c": 3}
keys = []
for key in m:
    keys.append(key)
print(sorted(keys))

vals = []
for v in m.values():
    vals.append(v)
print(sorted(vals))

pairs = []
for k, v in m.items():
    pairs.append(k)
print(sorted(pairs))

# Dict comprehension
squares = {x: x * x for x in range(6)}
print(sorted(squares.items()))

# Equality
print({"a": 1, "b": 2} == {"b": 2, "a": 1})
print({"a": 1} == {"a": 2})
print({} == {})

# Nested dict
nested = {"outer": {"inner": 42}}
print(nested["outer"]["inner"])

# fromkeys
fk = dict.fromkeys(["a", "b", "c"], 0)
print(sorted(fk.items()))

# Integer keys
nums = {1: "one", 2: "two", 3: "three"}
print(nums[1])
print(nums[3])
print(sorted(nums.keys()))
