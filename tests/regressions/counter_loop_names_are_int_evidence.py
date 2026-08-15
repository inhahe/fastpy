"""A counter loop's variable must count as evidence that a parameter is an int.

`_duf_select_abi` requires *positive* evidence -- an annotation or a
classifiable call site -- before giving a function the bare scalar ABI, because
`param_types` falls back to `i64` when nothing is known and "no evidence" and
"known to be an int" were otherwise indistinguishable
(BUG-UNTYPED-PARAM-BARE-ABI).

`_csa_build_var_types` has no arm for a plain int constant, though. `str`,
`float`, `complex` and bigint-magnitude ints are all recorded; `i = 0` records
nothing. That was harmless while `int` was also the fallback for "no evidence",
and stopped being harmless the moment silence began denying the bare ABI: the
single most ordinary shape in Python,

    def add(a, b):
        return a + b
    while i < N:
        total = total + add(i, 1)
        i = i + 1

classified `b` from the literal, found nothing for `a`, and emitted

    define internal {i32, i64} @add({i32, i64} %a, {i32, i64} %b)

instead of the bare `i64`, boxing and unboxing a tagged FpyValue on every one
of ten million calls -- about 9x on the `function calls 10M` benchmark.

Guarded below, in the order the predicate can get them wrong:

- `while` and `for`-`range` counters, and `+=`, must prove int (the fast path).
- A name the module later rebinds to a str must *not*, even though its first
  binding is an int -- proving a name means proving all of its bindings, not
  the first one.
- A loop over a list proves nothing about the element.
- A BigInt anywhere in the program withdraws every claim, since overflow
  promotion can put a heap pointer in an int-tagged name.

Correct output requires only that fastpy agree with CPython; the ABI is an
optimisation and is asserted separately. What this file pins is that the
optimisation never changes an answer.
"""


def add(a, b):
    return a + b


def sink(v):
    return v


# ── while counter ──
total = 0
i = 0
while i < 10:
    total = total + add(i, 1)
    i = i + 1
print(total)

# ── for-range counter ──
t2 = 0
for j in range(10):
    t2 = t2 + add(j, 1)
print(t2)

# ── augmented assignment ──
t3 = 0
k = 0
while k < 10:
    t3 = t3 + add(k, 1)
    k += 1
print(t3)

# ── int first, str later: not an int ──
rebound = 5
print(sink(rebound))
rebound = "now a str"
print(sink(rebound))

# ── loop over a list of strs proves nothing ──
for w in ["abcd", "xy"]:
    print(len(w))

# ── a BigInt in the program withdraws the claim ──
big = 2 ** 70
m = 0
while m < 3:
    m = m + 1
print(m, big)

# ── literal-to-literal unpack, and a mutual reference through a swap ──
p, q = 3, 4
print(add(p, q))
p, q = q, p
print(add(p, q), p, q)

# A starred unpack must prove nothing either, but that cannot be pinned by
# output here: every non-starred name in one already loses its kind
# regardless of this pass (BUG-STARRED-UNPACK-LOSES-KIND). The decline is
# asserted directly against the IR instead, in
# `test_abi_selection.py::test_declines_on_starred_unpack`.
