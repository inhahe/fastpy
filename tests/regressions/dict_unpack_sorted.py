# Regression: inline sorted() on dict built via {**d1, **d2}

d1 = {"a": 1, "b": 2}
d2 = {"c": 3, "d": 4}
m = {**d1, **d2}

# Stored version
keys = sorted(m)
for k in keys:
    print(k, m[k])

print("---")

# Inline version (was broken: _is_int_keyed_dict returned True for {**d})
for k in sorted(m):
    print(k, m[k])

print("---")

# Single unpack
m2 = {**d1}
for k in sorted(m2):
    print(k, m2[k])

print("---")

# Mixed unpack + literal
m3 = {**d1, "e": 5}
for k in sorted(m3):
    print(k, m3[k])
