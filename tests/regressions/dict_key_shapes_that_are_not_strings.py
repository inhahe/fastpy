# BUG-DICTCOMP-FV-KEY-EMITS-BROKEN-IR
# BUG-DICT-IN-COERCES-NON-STR-KEY-TO-CHAR-PTR
# BUG-FLOAT-KEY-DICT-LITERAL-SEGFAULTS
#
# Four emitters dispatched on a dict key's *LLVM type* inline, each with its
# own set of arms, and each was missing a different one.
#
#   * The dict-comprehension setters had no `fpy_val` arm and bailed to the
#     bridge from inside an already-emitted loop, stranding `dc.incr`/`dc.end`
#     unterminated:  `{i: m[i] for i in range(1)}` failed the *build* with
#     "expected instruction opcode" as soon as a BigInt anywhere in the
#     function promoted the loop variable to a tagged struct.
#
#   * `in` against a dict coerced any non-str key to a `char*` and strcmp'd it,
#     so `2.5 in {"a": 1}` reinterpreted the double's bit pattern as a pointer
#     and segfaulted — on a comparison whose answer is just False.
#
#   * A comprehension's *key* is an FV-backed variable in exactly the way its
#     value is, and arrives as a bare i64 payload, so `{k: 1 for k in m}` for a
#     heterogeneous `m` filed every key in the int-keyed table under the
#     string's address.
#
#   * No emitter had a *float* arm at all, on either side.  `{2.5: "a"}` fell
#     to the CPython bridge, and the PyObject that came back was then handed to
#     `len` as a native `FpyDict*` — a segfault on a two-entry dict literal.
#     Nothing was missing from the table itself: `fpy_hash_value` hashes a
#     FLOAT-tagged key already.
#
# The setters now share `_emit_dict_store_by_key` and the getters
# `_emit_dict_load_by_key`, which is what stops the arms from drifting apart
# again — and a store arm with no matching load arm is worse than neither,
# because the value goes in and cannot come back out.

# --- the build failure: one BigInt is enough to promote the loop variable ---
big = [2 ** 80]
c0 = {i: big[i] for i in range(1)}
print(c0)

mixed = [3, True, 4.5, "s", None, 2 ** 80]
c1 = {i: mixed[i] for i in range(6)}
print(c1)
print(c1[2], c1[3], c1[5])

# --- `in` with a key that is not a string, against a str-keyed dict ---
d = {"a": 1, "b": 2}
print(2.5 in d, 7 in d, "a" in d, "zz" in d)
print(2.5 not in d, "a" not in d)

# --- a dict whose keys are themselves runtime-tagged ---
m = ["a", 7, True, None]
ks, kn, kt, ko = m[0], m[1], m[2], m[3]
e = {ks: 1, kn: 2}
print(e)
print(e["a"], e[7])
print("a" in e, 7 in e, 2.5 in e, "zz" in e)

# --- the same keys arriving through a comprehension ---
f = {k: 1 for k in ["a", 7, True, None]}
print(f)
g = {k: 1 for k in m}
print(g)
print("a" in g, 7 in g)

# --- comprehension key/value pairs, both sides tagged ---
h = {mixed[i]: mixed[i] for i in range(5)}
print(h)

# --- subscript store with a tagged key ---
j = {}
j[ks] = 1
j[kn] = 2
print(j, j["a"], j[7])
print("a" in j, 7 in j)

# --- membership against a dict built by a nested comprehension ---
n2 = {a * 10 + b: (a, b) for a in range(2) for b in range(2)}
print(sorted(n2.keys()))
print(n2[11], 11 in n2, 99 in n2)

# --- float keys: the literal that used to segfault `len` ---
fd = {2.5: "a", 7: "b"}
print(len(fd))
print(fd[2.5], fd[7])
print(fd)
print(2.5 in fd, 7 in fd, 3.5 in fd, 2.5 not in fd)

# --- every way a float key can arrive ---
fd[1.5] = "c"          # subscript store
fk = 2.5               # a plain float variable
print(fd[fk], fd[1.5], len(fd))

fc = {x / 2: str(x) for x in range(4)}   # comprehension key
print(fc)
print(fc[0.0], fc[0.5], fc[1.0], fc[1.5])
print(0.5 in fc, 2.0 in fc)

# --- a float key read back inside a loop, where the key is not a constant ---
for kk in [0.0, 0.5, 1.0, 1.5]:
    print(kk, fc[kk])

# --- floats alongside every other key shape in one table ---
mix = {}
mix["s"] = 1
mix[2] = 2
mix[3.5] = 3
mix[(4, 5)] = 4
print(mix["s"], mix[2], mix[3.5], mix[(4, 5)], len(mix))
print("s" in mix, 2 in mix, 3.5 in mix, (4, 5) in mix, 9.5 in mix)

# --- the numeric tower is one key space: 1, 1.0 and True name one slot ---
# `fpy_hash_value` always hashed an integral 1.0 as 1, but `fpy_key_equal`
# rejected any tag mismatch, so the two hashed into the same bucket and then
# compared unequal — the dict kept both.  The int-specialized paths had their
# own, narrower rule again, which is why `{2.0: 'x'}[2]` raised a KeyError
# while `{2: 'x'}[2.0]` worked.
same = {1: "int"}
same[1.0] = "float"
same[True] = "bool"
print(same, len(same), same[1], same[1.0], same[True])

other = {1.0: "float"}
other[1] = "int"
print(other, len(other), other[1], other[1.0])
print(1 in other, 1.0 in other, True in other, 2 in other, 2.0 in other)

# --- the key object that was inserted first is the one that is kept ---
bk = {True: "bool"}
bk[1] = "int"
print(bk, len(bk), sorted(bk.keys()))
zk = {0: "zero"}
zk[False] = "false"
print(zk, len(zk))
tf = {True: 1, False: 0}
print(tf, tf[True], tf[1], tf[0], tf[False])

# --- but only when they are genuinely equal ---
frac = {0.5: "half", 1: "one", 2.0: "two"}
print(frac, len(frac), frac[0.5], frac[1.0], frac[2])

# --- a large integral float equals its int, and hashing must agree ---
big10 = 10 ** 18
lf = {big10: "int"}
lf[1e18] = "float"
print(len(lf), lf[big10], lf[1e18])

# --- an int no double can represent stays a key of its own ---
exact = {2 ** 60 + 1: "a"}
exact[float(2 ** 60)] = "b"
print(len(exact), exact[2 ** 60 + 1])

# --- sets follow the same rule ---
ns = {1, 1.0, True, 2, 0.5}
print(len(ns), 1 in ns, 1.0 in ns, True in ns, 0.5 in ns)
