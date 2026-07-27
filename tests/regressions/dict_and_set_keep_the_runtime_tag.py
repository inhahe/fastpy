# BUG-DICT-VALUE-STATIC-KIND
#
# Storing a runtime-tagged value into a dict or a set threw the tag away.
# Codegen reached for `_bare_to_tag_data`, whose contract is "bare value in,
# *static* tag out", so every store passed the constant `FPY_TAG_INT` and the
# container kept the payload word under the wrong type:
#
#   {"f": fl}   with fl = 4.5   read back 4616752568008179712  (the bit pattern)
#   {"s": st}   with st = "s"   read back the string's address
#   {"o": no}   with no = None  read back 0
#   s.add(fl); fl in s          was False (a bit pattern never matches a float)
#
# The load side was already right — the runtime has `dict_get_fv` with tag
# out-params — so only the stores lied.  The fix routes them through
# `_to_tag_data_ir`, which was extended to recognise the shape that actually
# matters here: an FV-backed *variable*.  `_emit_expr_value` hands a Name back
# as the bare i64 payload, so the struct test in that helper used to miss it.
#
# Every value below comes out of a heterogeneous list, which is what makes it
# runtime-tagged rather than a compile-time constant.

m = [3, True, 4.5, "s", None]
n, t, fl, st, no = m[0], m[1], m[2], m[3], m[4]

# --- dict literal with str keys ---
d = {"n": n, "t": t, "f": fl, "s": st, "o": no}
print(d["n"], d["t"], d["f"], d["s"], d["o"])
print(d)
print(sorted(d.keys()))
for k in sorted(d.keys()):
    print(k, d[k])

# --- subscript store into an empty dict ---
e = {}
e["t"] = t
e["f"] = fl
e["s"] = st
e["o"] = no
print(e["t"], e["f"], e["s"], e["o"])
print(e)
print(len(e), "f" in e, "zz" in e)

# --- int keys go through the int-keyed setter ---
g = {}
g[1] = fl
g[2] = st
g[3] = no
print(g[1], g[2], g[3], g)

# --- tuple keys go through the FpyValue-keyed setter ---
h = {(1, 2): fl}
h[(3, 4)] = st
print(h[(1, 2)], h[(3, 4)])

# --- dict comprehensions, both the range and the list-iteration shape ---
c = {i: m[i] for i in range(5)}
print(c)
print(c[1], c[2], c[3], c[4])

vals = [x for x in m]
c2 = {str(i): vals[i] for i in range(5)}
print(c2)

c3 = {k: v for k, v in [("a", fl), ("b", st), ("c", no)]}
print(c3["a"], c3["b"], c3["c"])

# --- the value survives being read back out and used ---
print(d["f"] + 1, d["f"] * 2, d["s"] * 2, d["t"] + 1)
# (`e["o"] is None` would belong here, but `is None` against a runtime-tagged
# value is a separate defect — BUG-IS-NONE-ON-TAGGED-VALUE.)
print(e["f"] > 4, e["s"] == "s", str(e["o"]))

# --- sets: the element is stored tag-and-all, so membership must match ---
s1 = {n, t, fl, st}
print(len(s1))
print(fl in s1, st in s1, n in s1, 99 in s1, "zz" in s1)

s2 = set()
s2.add(fl)
s2.add(st)
s2.add(no)
print(len(s2), fl in s2, st in s2, no in s2)
s2.discard(fl)
print(len(s2), fl in s2, st in s2)

# --- a dict of dicts, so the value is a pointer rather than a scalar ---
inner = {"f": fl}
outer = {"i": inner}
print(outer["i"]["f"])

# --- values written in a loop, which is where the tag is least static ---
acc = {}
for i in range(5):
    acc[i] = m[i]
print(acc)
print(acc[2] + 0.5, acc[3] + "!", str(acc[4]))
