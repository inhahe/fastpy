# Regression: d[k].items() / d[k].keys() crash when d is a dict comprehension
#
# Bug: Dict comprehension values are stored as FpyValues.  Subscripting
# the outer dict returned an FpyValue with tag=DICT.  Method calls like
# .items()/.keys() on this FV went through the CPython bridge, which
# returned a dict_items view.  pyobject_to_fpy didn't recognize dict_items,
# so it stored it as an opaque OBJ-tagged pointer.  The compiled code then
# tried to iterate/subscript it as a native FpyList, causing a segfault.
#
# Fix (two parts):
#   1. _assign_detect_dict_value_types now handles DictComp, so dict-of-dicts
#      from comprehensions get properly registered in _dict_var_dict_values.
#   2. pyobject_to_fpy now converts unknown iterables (dict_items, dict_keys,
#      dict_values, map, filter, etc.) to native lists via PySequence_List
#      before falling through to the opaque OBJ tag.

# Case 1: iterate items of inner dict from dict comp
d = {i: {j: i*j for j in range(3)} for i in range(3)}
for k in sorted(d.keys()):
    print(k, sorted(d[k].items()))

# Case 2: iterate keys of inner dict
d2 = {i: {0: i} for i in range(3)}
for k in sorted(d2.keys()):
    inner = d2[k]
    for ik in inner.keys():
        print(k, ik)

# Case 3: len of inner items
d3 = {i: {j: j for j in range(i+1)} for i in range(3)}
for k in sorted(d3.keys()):
    print(k, len(d3[k].items()))

# Case 4: sorted inner items
d4 = {0: {2: "b", 1: "a", 0: "c"}}
print(sorted(d4[0].items()))
