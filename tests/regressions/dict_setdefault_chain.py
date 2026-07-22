# Regression: d.setdefault("a", []).append(1) chained mutation
#
# Bug: setdefault returns an FpyValue {tag=LIST, data=ptr}.  When .append()
# was called on the FV receiver, the dispatch routed through the CPython
# bridge (fpy_fv_call_method1) which converts the FpyList to a Python list,
# calls append on the *copy*, and the original dict entry was never modified.
#
# Fix: _is_list_expr now recognises dict.setdefault(key, list_default) as a
# list expression, so the method dispatch routes to the direct
# fastpy_list_append_fv path (in-place on the dict's list pointer).

# Case 1: basic setdefault + append chain
d = {}
d.setdefault("a", []).append(1)
d.setdefault("a", []).append(2)
d.setdefault("a", []).append(3)
print(d["a"])

# Case 2: setdefault + extend chain
d2 = {}
d2.setdefault("x", []).extend([10, 20])
print(d2["x"])

# Case 3: two-step pattern (already works — control case)
d3 = {}
lst = d3.setdefault("k", [])
lst.append(100)
print(d3["k"])

# Case 4: multiple keys
d4 = {}
d4.setdefault("a", []).append(1)
d4.setdefault("b", []).append(2)
d4.setdefault("a", []).append(3)
print(d4["a"])
print(d4["b"])

# Case 5: setdefault where key already exists
d5 = {"x": [10]}
d5.setdefault("x", []).append(20)
print(d5["x"])
