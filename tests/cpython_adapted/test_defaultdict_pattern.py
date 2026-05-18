# Adapted from CPython Lib/test/test_defaultdict.py
# Tests defaultdict-like patterns (using plain dict)

# Counting pattern (Counter-like)
def count_items(items):
    counts = {}
    for item in items:
        if item in counts:
            counts[item] = counts[item] + 1
        else:
            counts[item] = 1
    return counts

# Word frequency
text = "the cat sat on the mat the cat"
words = text.split()
freq = count_items(words)
print(sorted(freq.items()))

# Character frequency
char_freq = count_items("abracadabra")
print(sorted(char_freq.items()))

# Grouping pattern (defaultdict(list)-like)
def group_by(items, key_func):
    groups = {}
    for item in items:
        k = key_func(item)
        if k in groups:
            groups[k].append(item)
        else:
            groups[k] = [item]
    return groups

# Group by length
words2 = ["cat", "dog", "fish", "bird", "ant", "cow", "bear", "fox"]
by_length = group_by(words2, len)
for k in sorted(by_length.keys()):
    print(k, sorted(by_length[k]))

# Group numbers by parity
numbers = list(range(10))
by_parity = group_by(numbers, lambda x: "even" if x % 2 == 0 else "odd")
print(sorted(by_parity["even"]))
print(sorted(by_parity["odd"]))

# Accumulator pattern (defaultdict(int)-like)
def accumulate(pairs):
    totals = {}
    for key, value in pairs:
        if key in totals:
            totals[key] = totals[key] + value
        else:
            totals[key] = value
    return totals

sales = [("apples", 3), ("bananas", 2), ("apples", 5),
         ("bananas", 1), ("cherries", 4), ("apples", 2)]
totals = accumulate(sales)
print(sorted(totals.items()))

# Nested defaultdict pattern (dict of dicts)
def nested_set(d, keys, value):
    for key in keys[:-1]:
        if key not in d:
            d[key] = {}
        d = d[key]
    d[keys[-1]] = value

tree = {}
nested_set(tree, ["a", "b", "c"], 1)
nested_set(tree, ["a", "b", "d"], 2)
nested_set(tree, ["a", "e"], 3)
print(tree["a"]["b"]["c"])
print(tree["a"]["b"]["d"])
print(tree["a"]["e"])

# Set-valued grouping (defaultdict(set)-like)
def group_unique(items, key_func):
    groups = {}
    for item in items:
        k = key_func(item)
        if k in groups:
            groups[k].add(item)
        else:
            groups[k] = {item}
    return groups

values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 1, 2, 3]
by_mod3 = group_unique(values, lambda x: x % 3)
for k in sorted(by_mod3.keys()):
    print(k, sorted(by_mod3[k]))

# Most common (Counter.most_common-like)
def most_common(counts, n):
    items = list(counts.items())
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:n]

letter_counts = count_items("mississippi")
print(most_common(letter_counts, 3))

# Setdefault pattern
def add_to_group(groups, key, value):
    if key not in groups:
        groups[key] = []
    groups[key].append(value)

g = {}
add_to_group(g, "fruits", "apple")
add_to_group(g, "fruits", "banana")
add_to_group(g, "vegs", "carrot")
add_to_group(g, "fruits", "cherry")
print(sorted(g["fruits"]))
print(g["vegs"])
