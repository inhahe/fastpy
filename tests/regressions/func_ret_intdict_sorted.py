# Regression: function-returned int-keyed dict with sorted keys iteration
# Tests that _is_int_keyed_dict correctly detects int keys in dicts
# returned from functions, so sorted(g.keys()) iteration variables are
# typed as int (not string).

def group_by_length(words):
    groups = {}
    for w in words:
        k = len(w)
        if k not in groups:
            groups[k] = []
        groups[k].append(w)
    return groups

words = ["hi", "hey", "hello", "yo", "yes", "no"]
g = group_by_length(words)
for k in sorted(g.keys()):
    print(k, sorted(g[k]))
