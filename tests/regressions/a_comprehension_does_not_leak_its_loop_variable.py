# Regression: a comprehension has its own scope, so its target must not
# overwrite an enclosing name.
#
# fastpy emits a comprehension inline in the enclosing scope, taking the
# generator target's name verbatim (`var_name = gen.target.id`) and storing
# through it with `force_type=True`.  That wrote straight over any enclosing
# binding of the same name -- and `force_type=True` replaced its *kind* as well
# as its value, so an outer `s` holding a string silently became an int, or
# became a different string.  Exit code 0, no diagnostic: the program simply
# computed with the wrong data (BUG-COMPREHENSION-LEAKS-ITS-LOOP-VARIABLE).
#
# The fix alpha-renames every comprehension's targets to internal names before
# any analysis pass runs, so the enclosing name is never a store target.  This
# file pins the observable half of that: the outer name keeps its value AND its
# type, across all four comprehension forms, at module and function scope, and
# in the shapes where the renaming is easy to get wrong -- nested
# comprehensions, a target that shadows an outer name used in the *first*
# iterable, tuple-unpacking targets, and a walrus (which really does bind in
# the enclosing scope and so must NOT be renamed).

# --- 1. All four forms leave the enclosing binding alone ------------------
p = "outer"
xs = [p for p in range(3)]
print(p, len(p), xs[0], xs[2])          # outer 5 0 2

q = "outer"
ys = {q for q in range(3)}
print(q, len(q), len(ys))               # outer 5 3

r = "outer"
zs = {r: r * 2 for r in range(3)}
print(r, len(r), zs[2])                 # outer 5 4

t = "outer"
gs = list(t for t in range(3))
print(t, len(t), gs[1])                 # outer 5 1

# A plain `for` loop, by contrast, genuinely *does* bind in the enclosing
# scope and must keep doing so.  This is the control: if the fix over-reached
# and gave for-loops their own scope too, this line would break.
u = "outer"
for u in range(3):
    pass
print(u)                                # 2

# --- 2. The kind is preserved, not just the value ------------------------
# This is the shape that made the bug dangerous: the leak retyped the name, so
# `len` and `.upper()` silently answered about the wrong object.
s = "hello world"
src = ["a", "b"]
copied = [s for s in src]
print(len(s))                           # 11
print(s.upper())                        # HELLO WORLD
print(copied[0], copied[1])             # a b

# A float outer name, which would read back as a bit pattern if retyped.
f = 2.5
fs = [f for f in range(3)]
print(f + 0.25)                         # 2.75
print(fs[2])                            # 2

# --- 3. Function scope ---------------------------------------------------
def keeps_its_local():
    name = "local"
    got = [name for name in ["x", "y", "z"]]
    return name + "/" + str(len(got))

print(keeps_its_local())                # local/3

def outer_survives_a_nested_comp():
    i = 100
    grid = [[j for j in range(2)] for i in range(3)]
    return i, len(grid), grid[2][1]

a, b, c = outer_survives_a_nested_comp()
print(a, b, c)                          # 100 3 1

# --- 4. The first iterable is evaluated in the ENCLOSING scope -----------
# `range(n)` here reads the outer `n`, not the comprehension's target, even
# though the target is also called `n`.  A rename that rewrote the first
# iterable too would turn this into a NameError or read the wrong value.
n = 4
ns = [n for n in range(n)]
print(n, len(ns), ns[3])                # 4 4 3

# The same with the outer name still a string afterwards.
w = "abc"
ws = [w for w in range(len(w))]
print(w, ws[2])                         # abc 2

# --- 5. Nested comprehensions and shadowing ------------------------------
# The inner comprehension's first iterable sees the OUTER comprehension's
# target -- that is a real dependency and must survive the rename.
outer = "kept"
pairs = [[k * 10 + m for m in range(k)] for k in range(4)]
print(outer, len(pairs))                # kept 4
print(len(pairs[0]), len(pairs[3]))     # 0 3
print(pairs[3][0], pairs[3][2])         # 30 32

# An inner comprehension whose target shadows the outer comprehension's.
z = "still here"
nested = [[z for z in range(2)] for z in range(3)]
print(z, len(nested), nested[2][1])     # still here 3 1

# --- 6. Tuple-unpacking targets ------------------------------------------
lo = "lo-outer"
hi = "hi-outer"
sums = [lo + hi for lo, hi in [(1, 2), (3, 4)]]
print(lo, hi)                           # lo-outer hi-outer
print(sums[0], sums[1])                 # 3 7

# --- 7. A walrus DOES bind in the enclosing scope ------------------------
# `:=` inside a comprehension deliberately assigns outside it.  It is not a
# generator target, so the rename must leave it alone.
seen = 0
walrus = [(seen := v) for v in range(5)]
print(seen)                             # 4
print(walrus[0], walrus[4])             # 0 4

# --- 8. Conditions and multiple generators -------------------------------
step = 3
c1 = "outer"
filtered = [c1 for c1 in range(10) if c1 % step == 0]
print(c1, len(filtered))                # outer 4
print(filtered[0], filtered[3])         # 0 9

g1 = "outer"
g2 = "outer"
prod = [g1 * 10 + g2 for g1 in range(3) for g2 in range(2)]
print(g1, g2)                           # outer outer
print(len(prod), prod[0], prod[5])      # 6 0 21
