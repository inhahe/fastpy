# Regression: dict subscript with key from sorted() stored in variable
# Previously crashed because _infer_call_type_tag assumed sorted(dict)
# always produces string keys, even for int-keyed dicts.

d = {5: 100, 2: 200, 8: 300}

# Direct iteration (always worked)
for k in sorted(d):
    print(k, d[k])

# Index into sorted result (always worked)
k = sorted(d)[0]
print(k, d[k])

# Stored sorted list + subscript — this was the crash
keys = sorted(d)
for k in keys:
    print(k, d[k])

# Variable index from stored sorted list
k2 = keys[1]
print(k2, d[k2])

# Also test sorted(d.keys()) stored
keys2 = sorted(d.keys())
for k in keys2:
    print(k, d[k])
