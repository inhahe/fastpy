# Regression: appending tuples to a list, then iterating + subscripting.
# Before fix: `pairs[0]` returned raw i64 data without using runtime tag,
# so `pairs[0][1]` gave a garbage pointer-as-int for string elements.

# Basic case: list of (int, str) tuples
pairs = []
pairs.append((1, "a"))
pairs.append((2, "b"))
pairs.append((3, "c"))

for p in pairs:
    print(p[0], p[1])

# Sort and access pattern (common idiom)
counts = {"alice": 30, "bob": 25, "charlie": 35}
items = []
for k in counts.keys():
    items.append((counts[k], k))
items.sort()
for item in items:
    print(item[1], item[0])

# Tuple literal in list literal
data = [(1, 2), (3, 4), (5, 6)]
for x, y in data:
    print(x + y)
