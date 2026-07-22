# Regression: dict comprehension with enumerate tuple unpacking
# Bug: {i: w for i, w in enumerate(seq)} stored keys as INT via
# dict_set_int_fv, but _is_int_keyed_dict didn't detect the enumerate
# tuple-unpacking pattern (only checked Name targets, not Tuple).
# During iteration, keys were typed as STR → access violation on d[k].
# Fix: added enumerate tuple-unpacking detection to _is_int_keyed_dict.

# Case 1: basic iterate + subscript
words = ["hello", "world", "foo"]
d = {i: w for i, w in enumerate(words)}
for k in d:
    print(k, d[k])

# Case 2: sorted keys + subscript
d2 = {i: w for i, w in enumerate(["c", "a", "b"])}
for k in sorted(d2.keys()):
    print(k, d2[k])

# Case 3: literal key subscript (always worked)
d3 = {i: w for i, w in enumerate(["x", "y", "z"])}
print(d3[0])
print(d3[1])
print(d3[2])

# Case 4: with start parameter
d4 = {i: w for i, w in enumerate(["a", "b", "c"], start=1)}
for k in sorted(d4.keys()):
    print(k, d4[k])

# Case 5: dict comp from enumerate with value transformation
nums = [10, 20, 30]
d5 = {i: v * 2 for i, v in enumerate(nums)}
for k in sorted(d5.keys()):
    print(k, d5[k])

# Case 6: dict comp from enumerate, non-int key (str key from value)
words2 = ["alpha", "beta", "gamma"]
d6 = {w: i for i, w in enumerate(words2)}
for k in sorted(d6.keys()):
    print(k, d6[k])
