"""Test dict comprehension with if-clause filter (tuple unpacking path)."""
src = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}

# Filter: only keep values > 2
big = {k: v for k, v in src.items() if v > 2}
print(sorted(big.items()))
# Expected: [('c', 3), ('d', 4), ('e', 5)]

# Filter: only keep even values
evens = {k: v for k, v in src.items() if v % 2 == 0}
print(sorted(evens.items()))
# Expected: [('b', 2), ('d', 4)]

# No filter (baseline)
all_items = {k: v for k, v in src.items()}
print(sorted(all_items.items()))
# Expected: [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)]

print("dict comp filter tests passed!")
