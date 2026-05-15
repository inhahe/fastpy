# Regression: del d[int_key] crashes (segfault)
#
# Bug: fastpy_dict_delete only accepted string keys (const char*).
# When del d[2] was emitted, the integer key (i64) was passed where
# a pointer was expected, causing an access violation.
#
# Fix: Added fastpy_dict_delete_int for integer keys and dispatch
# on the key's IR type in _emit_delete.

# Case 1: basic int key deletion
d = {0: "a", 1: "b", 2: "c", 3: "d"}
del d[2]
print(sorted(d.keys()))
print(d[0], d[1], d[3])

# Case 2: delete from loop-built dict
d2 = {}
for i in range(5):
    d2[i] = i * i
del d2[2]
del d2[4]
print(sorted(d2.keys()))
print(d2[0], d2[1], d2[3])

# Case 3: string key deletion still works
d3 = {"a": 1, "b": 2, "c": 3}
del d3["b"]
print(sorted(d3.keys()))

# Case 4: delete and re-add
d4 = {1: 10, 2: 20, 3: 30}
del d4[2]
d4[2] = 200
print(sorted(d4.items()))

# Case 5: delete last remaining key
d5 = {42: "only"}
del d5[42]
print(len(d5))
print(d5)
