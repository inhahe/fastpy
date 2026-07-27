# BUG-DICTCOMP-FV-KEY-EMITS-BROKEN-IR
# BUG-DICT-IN-COERCES-NON-STR-KEY-TO-CHAR-PTR
#
# Three emitters dispatched on a dict key's *LLVM type* inline, each with its
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
# The setters now share `_emit_dict_store_by_key`, which is what stops the arms
# from drifting apart again.

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
