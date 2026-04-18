# Regression: list comprehension iterating over list-of-dicts where
# all dict values are ints. Before fix: `p["key"]` in the filter
# fell through to `fv_str` returning a string representation, causing
# `p["key"] >= 2` to compare i8* with i64.

# All-int values — the loop variable's dict values propagate as int.
scores = [{"a": 1}, {"a": 2}, {"a": 3}]
matching = [s for s in scores if s["a"] >= 2]
print(len(matching))

# Filter and extract
vals = [s["a"] for s in scores]
print(vals)

# Sum over filtered
total = 0
for s in scores:
    if s["a"] >= 2:
        total = total + s["a"]
print(total)
