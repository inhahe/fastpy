# Regression: dict built from range/enumerate loop inside a function,
# then returned and iterated. Tests that _func_returns_int_keyed_dict
# detects for-loop variables (from range/enumerate) as int variables
# when used as dict keys.

# range-based
def make_squares():
    d = {}
    for i in range(5):
        d[i] = i * i
    return d

sq = make_squares()
for k in sorted(sq.keys()):
    print(k, sq[k])

# enumerate-based
def index_items(items):
    d = {}
    for i, item in enumerate(items):
        d[i] = item
    return d

result = index_items(["apple", "banana", "cherry"])
for k in sorted(result.keys()):
    print(k, result[k])

# Module-level range dict (also should work)
counts = {}
for n in range(1, 6):
    counts[n] = n * n * n
for k in sorted(counts.keys()):
    print(k, counts[k])
