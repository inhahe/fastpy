# BUG-BIGINT-TRUEDIV-UNIMPLEMENTED
#
# `/` was the one arithmetic operator with no BigInt implementation. The arm in
# fastpy_fv_binop left `case 3` empty and fell out of the block, and the codegen
# guard that keeps native pointers away from the CPython bridge did not list
# BIGINT — so `(2 ** 80) / 2` handed PyNumber_TrueDivide a raw FpyBigInt* and
# took an access violation.
#
# The interesting part of the fix is that the quotient cannot be computed by
# converting each side to a double first: (10 ** 400) / (10 ** 399) is exactly
# 10.0 even though neither operand is representable. It is computed from the
# magnitudes at 55 bits and scaled, with any remainder folded into the low bit
# so the single rounding lands where CPython's does.

big = 2 ** 80
print(big / 2)
print(big / big)
print(big / (2 ** 79))
print(2 / big)
print(-big / 2)
print(big / -2)
print(-big / -2)

# Neither side fits in a double, but the quotient is exact.
print((10 ** 400) / (10 ** 399))
print((2 ** 1000) / (2 ** 999))
print((3 ** 500) / (3 ** 499))

# A quotient that is not exact still has to be the correctly rounded double,
# which is what the sticky bit is for.
print((10 ** 400) / (3 * 10 ** 399))
print((2 ** 100 + 1) / (2 ** 100))
print(big / 3)

# The result crossing back into ordinary float range.
print((2 ** 200) / (2 ** 100))
print(1 / big)

# Zero divisor raises rather than crashing or answering 0.
try:
    big / 0
except ZeroDivisionError as e:
    print("zde:", e)

try:
    big // 0
except ZeroDivisionError as e:
    print("zde//:", e)

try:
    big % 0
except ZeroDivisionError as e:
    print("zde%:", e)

# A quotient too large for a double is an OverflowError, not inf.
try:
    print((10 ** 400) / 2)
except OverflowError as e:
    print("ovf:", e)

# Underflow goes to zero, as it does in CPython.
print(1 / (10 ** 400))

# Mixing a BigInt with a float is float arithmetic — this used to reinterpret
# the float's bit pattern as an integer.
print(big + 0.5)
print(big * 2.0)
print(0.5 + big)
print(big - 0.25)

# The ops that were already implemented must still work, and still demote to a
# plain int when the result fits.
print(big + 1)
print(big - big)
print(big * 2)
print(big // 3)
print(big % 7)
print((big + 1) - big)

# Floor division and modulo follow Python's sign rules, not C's.
print(-7 // 2, -7 % 2, 7 // -2, 7 % -2)
print((-big) // 3, (-big) % 3)
print(-7.0 // 2.0, -7.0 % 2.0)

# The dynamic path — values in a list are tagged, so they go through the same
# runtime binop rather than the statically-typed one.
vals = [2 ** 80, 2, 0.5]
print(vals[0] / vals[1])
print(vals[0] + vals[2])
print(vals[0] // vals[1])
