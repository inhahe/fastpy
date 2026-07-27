"""A container element's tag comes from the same inference on store and read.

BUG-LIST-LITERAL-BIGINT-DECIMAL-ELEM and the four bugs it uncovered.

BigInt, Decimal and complex are all *heap* numbers: an FpyValue holds a
pointer in its data slot, and only the tag says so.  A list literal used to
store them with the generic fall-through, which tags every i64 INT and every
pointer STR — so `[2 ** 80]` printed the element's address and
`[Decimal("1.5")]` printed an empty line.  A *dict* held the same values
correctly all along, because `_bare_to_tag_data` consults `_infer_type_tag`
while the list-literal path consulted the much weaker `_is_*_expr`
predicates.  (`_is_bigint_expr` knows only a too-wide integer literal and a
BIGINT-kinded name, so it answers False for `2 ** 80` — a BinOp of two small
constants.)  Collapsing the store path onto `_infer_type_tag` is the fix.

Storing the tag correctly then exposed the reads:

  * `_infer_list_elem_type` had no arm for the three kinds, so they fell
    through to the INT default, `_can_inline_list_access` said "int", and
    `c[0]` became an inline i64 load of the *pointer*.
    BUG-LIST-ELEM-TYPE-MISSES-HEAP-NUMERICS.
  * `_is_complex_expr` had no Subscript arm, so `c[0] + c[1]` typed the
    enclosing BinOp INT and printed the result FpyComplex* as an integer.
    BUG-COMPLEX-SUBSCRIPT-NOT-COMPLEX-EXPR.
  * The UNKNOWN⊗INT binop split had a two-way "both INT, else float via
    bitcast" shape — the third copy of that anti-pattern — so
    `[Decimal("1.5"), 1][0] + 1` read the Decimal's address as a denormal
    double.  BUG-UNKNOWN-INT-BINOP-FLOAT-EDGE.
  * Its new generic edge landed in `fastpy_fv_binop`, which had no Decimal
    or complex arms at all and fell into integer arithmetic on the pointer.
    BUG-FV-BINOP-NO-DECIMAL-COMPLEX.
  * `sum()`'s only two accumulators are i64 and double, both read with
    `_list_get_as_bare(..., "int")`, which throws the tag away.
    BUG-SUM-BARE-I64-OVER-HEAP-ELEMENTS.

Comparison had the mirror-image hole.  `_emit_compare` has a BIGINT arm but
none for Decimal or complex, and two Decimals share a *kind*, so they also
missed the cross-type `fv_compare` branch (which requires the two kinds to
differ) and fell to the generic pointer compare at the bottom:
`Decimal("1.5") < Decimal("2.5")` was answered on heap *address* order and
flipped from run to run.  BUG-DECIMAL-COMPLEX-COMPARE-BY-POINTER.  The arm
routes to `fastpy_fv_compare`, which had no Decimal or complex case either
(BUG-FV-COMPARE-NO-DECIMAL-COMPLEX), and `_is_decimal_expr` was missing the
same Subscript arm as `_is_complex_expr`
(BUG-DECIMAL-SUBSCRIPT-NOT-DECIMAL-EXPR).

And `print([1 + 2j])` aborted with STATUS_HEAP_CORRUPTION before printing
anything: `fpy_value_repr` called free() on `fpy_complex_to_str`'s result,
which unlike its BigInt/Decimal siblings is a *header-backed* buffer whose
char* points 8 bytes into the malloc block.
BUG-COMPLEX-REPR-FREES-HEADERED-STRING.
"""

from decimal import Decimal


# ── BigInt elements ──────────────────────────────────────────────────────

b = 2 ** 80
v = [2 ** 80, 1, -(2 ** 90), b, b * 2, 2 ** 80 + 1]
print(v)
print(v[0], v[1], v[2], v[3], v[4], v[5])
print(v[0] + 1, v[0] * 2, v[0] // 2, v[0] - 1)
print(v[0] == b, v[0] > 1, v[0] != 1, v[1] + 1)
print(len(v))

# The literal must agree with the same value stored through a name.
print(v[0] == b, v[3] == b, v[4] == b * 2)


# ── Decimal elements ─────────────────────────────────────────────────────

w = [Decimal("1.5"), Decimal("2.5") + 1, 1, Decimal("-0.25")]
print(w)
print(w[0], w[1], w[2], w[3])
print(w[0] + 1, w[0] * 2, w[0] - 1, w[0] + w[1])
print(w[0] == Decimal("1.5"), len(w))


# ── Complex elements ─────────────────────────────────────────────────────
# `print(c)` alone is the heap-corruption repro: it reaches fpy_value_repr's
# COMPLEX case, which the indexed reads below never do.

c = [1 + 2j, complex(0, 1), 3 + 0j]
print(c)
print(c[0], c[1], c[2])
print(c[0] + c[1], c[0] * 2, c[0] - c[1], c[0] + 1)
print(len(c))


# ── Nested and tuple containers take the same path ───────────────────────

n = [[2 ** 80], [Decimal("1.5")], [1 + 2j]]
print(n[0][0], n[1][0], n[2][0])

t = (2 ** 80, Decimal("1.5"), 1 + 2j, 7)
print(t)
print(t[0], t[1], t[2], t[3])


# ── A dict has always been right; the point is that the two agree ────────

d = {"big": 2 ** 80, "dec": Decimal("1.5"), "cpx": 1 + 2j}
print(d["big"], d["dec"], d["cpx"])
print(d["big"] == v[0], d["dec"] == w[0])


# ── sum() over heap-numeric elements ─────────────────────────────────────

print(sum([2 ** 80, 2 ** 80]))
print(sum([b, b, b], b))
print(sum([Decimal("1.5"), Decimal("2.5")]))
print(sum([1 + 2j, 3 + 4j]))
print(sum([b]) == b)

# …and the plain-scalar accumulators must be untouched.
print(sum([1, 2, 3]), sum([1, 2, 3], 10))
print(sum([1.5, 2.5]), sum([1.5, 2.5], 1.0))
print(sum([]), sum((1, 2, 3)), sum({1, 2, 3}))


# ── Comparison: the answer must not depend on heap addresses ─────────────

d0 = Decimal("1.5")
d1 = Decimal("2.5")
print(d0 < d1, d0 > d1, d0 <= d1, d0 >= d1, d0 == d1, d0 != d1)
print(d0 == Decimal("1.5"), d0 <= Decimal("1.5"), d0 >= Decimal("1.5"))
print(d0 < 2, d0 > 1, d0 == 1.5, 1 < d0, 2 > d0, 1.5 == d0)

# …including when one side is a container read and the other is not.
z = [Decimal("1.5"), Decimal("2.5")]
print(z[0] < z[1], z[0] > z[1], z[0] == d0, d0 < z[1], z[0] > d1)
print(w[0] == Decimal("1.5"), w[0] < w[1], w[0] < 2)

# complex compares for equality only; ordering is a TypeError even between
# two complexes, which the "same tag → compatible" shortcut used to let past.
q0 = 1 + 2j
q1 = 3 + 4j
print(q0 == complex(1, 2), q0 != q1, q0 == q1)
print(c[0] == q0, c[0] == c[1], c[0] != c[1], q0 == c[0])
print((1 + 0j) == 1, (1 + 0j) == 1.0, q0 == 1)
try:
    print(q0 < q1)
except TypeError as e:
    print("TypeError:", e)


# ── Iteration keeps the tag too ──────────────────────────────────────────

for x in [2 ** 80, 2 ** 81]:
    print(x)
for x in [Decimal("1.5"), Decimal("2.5")]:
    print(x)

total = 0
for x in v:
    total = total + x
print(total)
