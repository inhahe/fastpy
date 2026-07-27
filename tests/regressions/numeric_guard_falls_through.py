# BUG-BINOP-GUARDS-ENUMERATE-THE-FORBIDDEN
#
# Three separate guards in the arithmetic path were written as deny-lists —
# "these kinds must not continue" — and every one of them was missing entries:
#
#   * codegen's float fast path listed str/list/dict/set/tuple/bytes/obj, so a
#     BigInt, Decimal or complex operand had its *pointer* sitofp'd into a
#     double and `(2 ** 80) + 0.5` printed a heap address plus a half;
#   * codegen's BigInt fast path promoted the other operand with
#     bigint_from_i64(as_i64()), which for a float hands over the double's bit
#     pattern as an integer;
#   * fastpy_fv_binop's stop-here check listed the container tags, so BIGINT —
#     never on the list — fell into the plain i64 arithmetic at the bottom.
#
# They are positive checks now: name what is allowed, and an unhandled
# combination fails loudly instead of answering a plausible number.
#
# The same "plausible number instead of an error" theme covers the rest of this
# file: a zero divisor that returned 0 or nan, and `&` on a float that returned
# 0 because it fell through to the bridge's no-match answer.

big = 2 ** 80

# --- a native pointer kind mixed with a float ---
print(big + 0.5)
print(0.5 + big)
print(big * 2.0)
print(big - 0.25)
print(big / 0.5)
print(big // 2.0)

# --- pow still works on the statically-typed BigInt path ---
print(big ** 2)

# --- bit ops on a float are a TypeError, not 0 ---
try:
    print(1 & 1.5)
except TypeError as e:
    print("te&:", e)
try:
    print(1.5 | 1)
except TypeError as e:
    print("te|:", e)
try:
    print(1.5 ^ 2.5)
except TypeError as e:
    print("te^:", e)

# --- every zero divisor raises ---
try:
    print(1.0 / 0.0)
except ZeroDivisionError as e:
    print("f/:", e)
try:
    print(1.0 // 0.0)
except ZeroDivisionError as e:
    print("f//:", e)
try:
    print(1.0 % 0.0)
except ZeroDivisionError as e:
    print("f%:", e)
try:
    print(1 % 0)
except ZeroDivisionError as e:
    print("i%:", e)

# --- Python's sign rules for // and %, which C's operators do not share ---
print(-7 // 2, -7 % 2, 7 // -2, 7 % -2)
print(-7.0 // 2.0, -7.0 % 2.0, 7.0 // -2.0, 7.0 % -2.0)
print(-7.5 % 2.0, 7.5 % -2.0)

# --- Decimal and complex keep working; they were latent, not broken ---
from decimal import Decimal

c = 1 + 2j
print(c / 2, c * 3, c + 1.5, c - 0.5)
d = Decimal("1.5")
print(d / 2, d * 3, d + 1, d - 1)

# --- the dynamic path: values read out of a list carry runtime tags, so they
#     go through fastpy_fv_binop rather than a statically-typed emitter ---
vals = [2 ** 80, 1.5, 3, 2]
print(vals[0] + vals[1])
print(vals[0] / vals[3])
print(vals[0] % vals[2])
print(vals[1] % vals[2])
print(vals[2] // vals[3], vals[2] % vals[3])
try:
    print(vals[0] / 0)
except ZeroDivisionError as e:
    print("dyn zde:", e)

# --- comparisons across the int/float boundary are unaffected ---
print(big > 1e30, big < 1e30, big == 2 ** 80)
