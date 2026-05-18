# Adapted from CPython Lib/test/test_defaultdict.py
# Tests defaultdict-like patterns (using plain dict)
#
# NOTE: Avoids polymorphic function calls (same function called with
# both string and list args) and string keys in dicts passed through
# function parameters (lose type info). Uses monomorphic functions
# and module-level dict access for string-keyed dicts.

# Counting pattern (Counter-like) for strings
def count_words(items):
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
freq = count_words(words)
print(sorted(freq.items()))

# Counting pattern for integers
def count_numbers(items):
    counts = {}
    for item in items:
        if item in counts:
            counts[item] = counts[item] + 1
        else:
            counts[item] = 1
    return counts

nums = [1, 2, 3, 1, 2, 1, 4, 5, 1]
num_freq = count_numbers(nums)
print(sorted(num_freq.items()))

# Grouping pattern (defaultdict(list)-like)
def group_by_length(items):
    groups = {}
    for item in items:
        k = len(item)
        if k in groups:
            groups[k].append(item)
        else:
            groups[k] = [item]
    return groups

# Group by length
words2 = ["cat", "dog", "fish", "bird", "ant", "cow", "bear", "fox"]
by_length = group_by_length(words2)
for k in sorted(by_length.keys()):
    print(k, sorted(by_length[k]))

# Group numbers by parity (int key, list[int] value)
def group_by_parity(numbers):
    groups = {}
    for x in numbers:
        k = x % 2
        if k in groups:
            groups[k].append(x)
        else:
            groups[k] = [x]
    return groups

numbers = list(range(10))
by_parity = group_by_parity(numbers)
print(sorted(by_parity[0]))
print(sorted(by_parity[1]))

# Accumulator pattern with integer keys
def accumulate_int(pairs):
    totals = {}
    for key, value in pairs:
        if key in totals:
            totals[key] = totals[key] + value
        else:
            totals[key] = value
    return totals

int_sales = [(1, 3), (2, 2), (1, 5), (2, 1), (3, 4), (1, 2)]
int_totals = accumulate_int(int_sales)
print(sorted(int_totals.items()))

# Accumulator pattern inline (string keys, no function param)
str_totals = {}
for name, amount in [("apples", 3), ("bananas", 2), ("apples", 5),
                      ("bananas", 1), ("cherries", 4), ("apples", 2)]:
    if name in str_totals:
        str_totals[name] = str_totals[name] + amount
    else:
        str_totals[name] = amount
print(sorted(str_totals.items()))

# Nested dict access (inline, not through function)
tree = {}
tree["a"] = {}
tree["a"]["b"] = {}
tree["a"]["b"]["c"] = 1
tree["a"]["b"]["d"] = 2
tree["a"]["e"] = 3
print(tree["a"]["b"]["c"])
print(tree["a"]["b"]["d"])
print(tree["a"]["e"])

# Most common pattern
word_counts = count_words(["the", "cat", "sat", "the", "the", "cat", "on"])
mc_items = list(word_counts.items())
mc_items.sort(key=lambda x: x[1], reverse=True)
top3 = mc_items[:3]
print(top3)

# Setdefault pattern (inline)
g = {}
g["fruits"] = []
g["fruits"].append("apple")
g["fruits"].append("banana")
g["vegs"] = []
g["vegs"].append("carrot")
g["fruits"].append("cherry")
print(sorted(g["fruits"]))
print(g["vegs"])
