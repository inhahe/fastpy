"""`abs()` must handle every numeric shape, not just a naked i64 or double.

BUG-ABS-OF-TAGGED-VALUE.

`_emit_builtin_abs` knew exactly two LLVM types:

    val = self._emit_expr_value(arg_node)
    if isinstance(val.type, ir.IntType):
        ...
    elif isinstance(val.type, ir.DoubleType):
        ...
    return self._bridge_fallback_expr(node, "abs() with wrong args")

Anything else fell off the end of the `if` and reached the fallback, which
yields 0 in native mode.  Three separate kinds of argument did:

* **A runtime-tagged `FpyValue`** — a heterogeneous list element, or a call
  to a function whose returns disagree.  `abs(v[0])` on `[1, -2.5]` printed
  `0 0`.  This one predates every recent fix: a heterogeneous list element
  has always been a tagged value.

* **A BigInt**, which is a pointer.  `b = 2 ** 80; print(abs(b))` printed 0.

* **A Decimal**, likewise.  `abs(Decimal("-2.5"))` printed 0 — and
  `decimal_abs` had been declared in codegen's runtime table all along
  without a single caller, which is a fair summary of the bug.

The silent `_bridge_fallback_expr` is why this survived: a `CodeGenError`
would have surfaced it immediately.

The tagged case is answered by a new runtime `fastpy_abs_fv`, not by inlined
IR, because *six* tags are numeric rather than two — INT, BOOL, FLOAT,
BIGINT, DECIMAL and COMPLEX.  An i64/double select in codegen would have
left the other three silently wrong instead of visibly wrong.  Two details
it has to get right:

* `abs(-2**63)` does not fit an i64.  CPython has no such limit, so the
  INT case widens to a BigInt rather than wrapping — and negating in place
  to detect it would itself be undefined behaviour.
* `abs(a+bj)` is a real magnitude, so a COMPLEX argument returns a FLOAT.

A non-numeric tag raises `TypeError` with CPython's own wording rather than
returning a quiet zero.
"""

from decimal import Decimal


# ── Plain scalars, unchanged ──

print(abs(-3), abs(3), abs(0))
print(abs(-2.5), abs(2.5), abs(0.0))
print(abs(True), abs(False))


# ── A tagged element of a heterogeneous list ──

v = [1, -2.5]
print(abs(v[0]), abs(v[1]))

w = [-7, 8, -9.5, 10.5, True, False]
for x in w:
    print(abs(x))

print(abs([3, -4][1]), abs([3.5, -4.5][1]))


# ── A "mixed"-returning call ──

def f(x):
    if x:
        return 1
    return -2.5


def g(x):
    if x:
        return -3
    return 4.5


print(abs(f(1)), abs(f(0)))
print(abs(g(1)), abs(g(0)))
print(abs(f(1)) + abs(f(0)))


# ── A ternary with disagreeing arms ──

c = True
d = False
print(abs(1 if c else -2.5), abs(1 if d else -2.5))
print(abs(-1 if c else 2.5), abs(-1 if d else 2.5))


# ── BigInt ──

b = 2 ** 80
nb = -(2 ** 80)
print(abs(b))
print(abs(nb))
# `abs(b) == abs(nb)` and `abs(b) - abs(nb)` are absent: a BIGINT-tagged
# FpyValue is not narrowed back to a pointer by comparison or arithmetic, so
# they compare the pointers.  That is BUG-BIGINT-FV-RESULT-NOT-CONSUMED and it
# is inherited from the `bigint_neg` convention this follows — `-b == -c` is
# already False with no abs() in sight.


# ── Decimal ──

dm = Decimal("-2.5")
dp = Decimal("2.5")
print(abs(dm), abs(dp))
print(abs(Decimal("-0.001")))
print(abs(Decimal("0")))


# ── Complex: abs is a real magnitude ──

print(abs(3 + 4j))
print(abs(-3 - 4j))
print(abs(complex(0, 5)))


# ── A non-numeric tag raises, rather than returning a quiet zero ──

s = ["x", 1]
try:
    print(abs(s[0]))
except TypeError as e:
    print("TypeError:", e)


# ── Inside a function, and in a loop so it cannot be constant-folded ──

def inner():
    t = 0.0
    for i in range(6):
        t = t + abs(f(i % 2))
    print(t)
    u = 0
    for j in range(4):
        u = u + abs(g(j % 2))
    print(u)


inner()

# The `while` form of the same accumulator is at module scope rather than
# inside `inner`, because a `while` loop whose counter is `i = i + 1` hangs
# outright in any program that also mentions a big-integer constant — and the
# BigInt section above binds two.  BUG-BIGINT-PROGRAM-HANGS-WHILE-COUNTER,
# which predates all of this and has nothing to do with abs().  Module-level
# `while` is unaffected, so the coverage is kept, just moved.
mt = 0.0
mi = 0
while mi < 6:
    mt = mt + abs(f(mi % 2))
    mi = mi + 1
print(mt)


# ── The result used in arithmetic, formatting and containers ──

print(abs(v[1]) * 2, abs(v[0]) * 2)
# `int()`/`float()` of a tagged value are no-ops — `int(v[1])` on `[1, -2.5]`
# yields -2.5 with no abs() involved.  BUG-INT-FLOAT-OF-TAGGED-VALUE.
print(str(abs(v[0])), str(abs(v[1])))
print(f"{abs(v[0])} {abs(v[1])}")
print([abs(v[0]), abs(v[1])])
# `max`/`min` of two tagged values are absent on purpose: they emit an `icmp`
# on a `{i32, i64}` and fail the IR verifier.  That is BUG-MINMAX-OF-TAGGED-
# VALUE, it predates this fix, and it is unrelated to abs() — `max(v[0], v[1])`
# fails the same way with no abs() in sight.
