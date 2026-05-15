# Regression: building a dict by iterating a list (int keys from loop var)
# then iterating that dict. Tests that _is_int_keyed_dict detects
# d[loop_var] = ... inside for loops over int iterables.

def count_items(lst):
    counts = {}
    for item in lst:
        if item in counts:
            counts[item] += 1
        else:
            counts[item] = 1
    best = 0
    best_count = 0
    for item in counts:
        if counts[item] > best_count:
            best_count = counts[item]
            best = item
    return best

print(count_items([1, 2, 3, 2, 2, 1, 3, 2]))

# Module-level version
counts = {}
data = [10, 20, 30, 20, 10, 10]
for x in data:
    if x in counts:
        counts[x] += 1
    else:
        counts[x] = 1
for k in counts:
    print(k, counts[k])
