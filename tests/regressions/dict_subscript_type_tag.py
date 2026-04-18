# Regression: dict subscript type_tag for known-value-type dicts
# Before fix: _infer_type_tag returned "str" for d[key] even when d was a
# dict-of-lists or dict-of-dicts, causing the variable to be tagged as "str"
# and the FV to have tag=STR instead of tag=LIST/DICT.
# Fix: added dict subscript detection in _infer_type_tag that checks
# _dict_var_list_values, _dict_var_dict_values, _dict_var_int_values.

# Dict of lists
d = {"fruits": ["apple", "banana"], "vegs": ["carrot", "pea"]}
for category in sorted(d.keys()):
    items = d[category]
    print(f"{category}: {items}")

# Dict of dicts
nested = {"a": {"x": 1}, "b": {"y": 2}}
for k in sorted(nested.keys()):
    inner = nested[k]
    print(f"{k}: {inner}")

# Dict of ints
counts = {"x": 10, "y": 20, "z": 30}
for k in sorted(counts.keys()):
    val = counts[k]
    print(f"{k} = {val}")

# Dict of lists, iterate inner
groups = {"g1": [1, 2, 3], "g2": [4, 5, 6]}
for name in sorted(groups.keys()):
    for item in groups[name]:
        print(f"{name}: {item}")
