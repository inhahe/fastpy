# Regression: dict comprehension from list with integer keys
# Bug: {x: x**2 for x in nums} where nums is a list of ints stored
# keys via dict_set_int_fv (INT tag, fpy_hash_int) but iteration
# typed the loop variable as STR. When doing d[k] the key pointer
# was actually an integer (e.g. 1) treated as a char* pointer,
# causing access violation crashes in dict_get_fv.
# Fix: extended _is_int_keyed_dict to detect dict comps from list
# variables where key=iterator variable and list elements are ints.

# Case 1: iterate and subscript
nums = [1, 2, 3]
d = {x: x**2 for x in nums}
for k in d:
    print(k, d[k])

# Case 2: sorted keys + subscript
nums2 = [3, 1, 2]
d2 = {x: x**2 for x in nums2}
for k in sorted(d2.keys()):
    print(k, d2[k])

# Case 3: list(keys) + sort + subscript
nums3 = [10, 20, 30]
d3 = {x: x // 10 for x in nums3}
ks = list(d3.keys())
ks.sort()
for k in ks:
    print(k, d3[k])

# Case 4: variable key subscript
nums4 = [1, 2, 3]
d4 = {x: x * 10 for x in nums4}
k0 = list(d4.keys())[0]
print(d4[k0])

# Case 5: dict comp with str keys (still works)
words = ["hello", "world"]
sd = {w: len(w) for w in words}
for k in sorted(sd.keys()):
    print(k, sd[k])

# Case 6: dict comp from range (still works)
rd = {i: i*i for i in range(4)}
for k in sorted(rd.keys()):
    print(k, rd[k])
