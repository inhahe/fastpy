"""A BIGINT-tagged FpyValue must be read as a number, not as its pointer.

BUG-BIGINT-FV-RESULT-NOT-CONSUMED.

Runtime helpers that produce a BigInt hand it back as a *tagged* `FpyValue`
carrying the pointer in `data`.  Codegen was right all along — `-b` emits
`fpy_bigint_neg` and wraps the result in `{i32 10, i64 ptr}` — but two
consumers read that i64 as if it were the number:

* **`fastpy_fv_compare`** had no BIGINT case.  It handles STR, then "at least
  one is FLOAT", then falls through to a default integer compare, so
  `-b == -c` compared the two *pointers* and answered False for equal
  BigInts.  (`fpy_value_compare`, the qsort helper a thousand lines down the
  same file, got this right with `fpy_bigint_cmp` all along.)

* **`_emit_binop_unknown`** inlined a two-way `both tags == INT` test that
  branched to integer arithmetic or *float* arithmetic.  BIGINT is tag 10, so
  it took the float edge and had its pointer bitcast to a double: `-b - -c`
  printed `1024.0`.

That second one is BUG-ABS-OF-TAGGED-VALUE's shape exactly — an inlined
binary dispatch where six tags are numeric, not two — and it has the same
answer.  The runtime's `fastpy_fv_binop` already handles BigInt, Decimal,
string concatenation and the TypeErrors correctly and simply was not being
called.  The int and float fast paths stay inline; the float edge is now
guarded by a real "both operands are plain scalars" check, and everything
else takes a third edge to the runtime.

Two things the comparison fix has to get right beyond equality:

* **Ordering a BigInt against a float used to raise TypeError.** FLOAT was
  missing from the BIGINT row of `_fpy_tags_order_compatible`, so
  `2 ** 80 < 1.5` raised instead of answering.

* **That comparison must be exact.** Converting the BigInt to a double and
  comparing would round everything past 2^53, making `2**80 == 2.0**80 + 1`
  True.  Going the other way is exact below 2^63: the double's integer part
  converts to a BigInt losslessly and the fraction breaks the tie.
"""

from decimal import Decimal

b = 2 ** 80
c = 2 ** 80
n = -(2 ** 90)


# ── The two reported repros ──

print(-b == -c)
print(-b - -c)


# ── Equality and ordering among BigInts ──

print(b == c, b != c, b >= c, b <= c, b < c, b > c)
print(n < b, n <= b, n > b, n >= b)
print(-b == b, -b < b, -b != b)


# ── Arithmetic on negated BigInts, which is what produced the tagged value ──

print(-b + b)
print(-b + c)
print(-b * 2)
print(-b // 3)
print(-b % 7)
print(-(-b))
print(abs(-b) == abs(b))
print(abs(-b) + abs(b))


# ── BigInt against int and bool ──

print(b == 1, b > 1, b < 1, 1 < b, 1 > b)
print(b > True, True < b, b == True, False < b)
print(n < 0, n < -1, 0 > n)


# ── BigInt against float, which used to raise TypeError ──

print(b > 1.5, b < 1.5, 1.5 < b, 1.5 > b)
print(n < 1.5, n < -1.5, -1.5 > n)
print(b < 1e300, b > 1e300, b == 1e300)
print(b > 0.0, b >= 0.0, n < 0.0)


# ── Exactness: a double conversion would round these together ──
# 1208925819614629174706176.0 is exactly 2**80, and 2**80 ± 1 round to that
# same double.  So a comparison that goes through `(double)bigint` answers
# "equal" to all three, and only an exact one gets them right.
# `float(2 ** 80)` is deliberately not used to build the literal: `float()`
# of a tagged value is a no-op and hands back the BigInt unchanged.  That is
# BUG-INT-FLOAT-OF-TAGGED-VALUE, unrelated and still open.

big = 2 ** 80
print(big == 1208925819614629174706176.0)
print(big + 1 > 1208925819614629174706176.0)
print(big - 1 < 1208925819614629174706176.0)
print(big + 1 == 1208925819614629174706176.0)


# ── The float's fraction has to break a tie on the integer part ──

q = 10 ** 25
print(q > 1.5, q > -1.5)
print(big > 1208925819614629174706175.5)
print(big < 1208925819614629174706176.5)


# ── The generic edge must not disturb the plain scalar fast paths ──

m = [3, 4.5, True]
print(m[0] + m[1], m[1] - m[0], m[0] * m[1], m[0] // 2)
print(m[2] * m[1])
print(m[0] + 1, 1 + m[0], m[1] + 1, 1 + m[1])
# `m[2] + m[0]` — BOOL + INT out of a list — is absent: it prints `4.0`, not
# `4`.  Both operands are plain scalars, so it takes the same float edge it
# took before this fix, and the result is only wrong in its *type*.
# BUG-BOOL-PLUS-INT-YIELDS-FLOAT, pre-existing and unrelated.

s = ["a", "b"]
print(s[0] + s[1], s[0] * 3)

lists = [[1], [2]]
print(lists[0] + lists[1])


# ── Decimal goes down the same generic edge ──

d = Decimal("2.5")
print(d + 1, d * 2, d - 1)
# A Decimal *in a list* is absent on purpose: it loses its tag on the way in
# and comes back out tagged STR, so `dv[0]` alone prints the empty string
# with no arithmetic in sight.  BUG-LIST-LITERAL-BIGINT-DECIMAL-ELEM,
# pre-existing and unrelated.


# ── In a loop, so nothing can be constant-folded ──

def loop():
    tot = 0
    for i in range(4):
        tot = tot + (2 ** 80)
    print(tot)
    print(tot == 4 * (2 ** 80))
    k = -(2 ** 80)
    acc = 0
    for i in range(3):
        acc = acc + k
    print(acc)


loop()


# ── Through a function boundary ──

def neg(x):
    return -x


def eq(x, y):
    return x == y


print(eq(neg(b), neg(c)))
# `print(neg(b))` alone is absent: a bare BigInt returned through a call is a
# separate question from consuming a tagged one, and it is not what this test
# pins.  `neg(b) + b` is absent for the same reason and is worse — it prints a
# nonzero garbage number, because the BigInt loses its tag crossing the return
# boundary.  BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG, pre-existing.
