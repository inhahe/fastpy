# BUG-INT-FLOAT-OF-TAGGED-VALUE
#
# `int(x)` and `float(x)` knew two shapes: naked scalars, and an inlined
# branch over an FV-backed *variable*.  A tagged value arriving any other way
# — a heterogeneous list element, a "mixed"-returning call — matched neither
# and was handed straight back, tag and all, so `int(v[1])` on `[1, -2.5]`
# printed `-2.5` and `float(v[0])` printed `1`.
#
# The inlined variable branch was wrong in its own way: its else arm used the
# raw payload, which for a BigInt or a Decimal is a *pointer* — returned as
# the integer by `int()`, and `sitofp`-ed into a double by `float()` — and for
# None or a list invented a number where CPython raises.
#
# Both now dispatch in the runtime, which is also where the float→int edge
# cases live: `fptosi` is undefined outside the i64 range, so `int(1e30)` used
# to give 20 and `int(float("nan"))` / `int(float("inf"))` both gave
# INT64_MIN.

# --- the original repro: conversions of list elements ---
v = [1, -2.5]
print(int(v[1]))
print(float(v[0]))

# --- every scalar shape, as loop variables (so each is runtime-tagged) ---
for x in [7, -7, 2.9, -2.9, "42", " -13 ", True, False]:
    print(int(x), float(x))

# --- floats that do not fit an i64, and the ones that are not numbers ---
print(int(1e30))
print(int(-1e30))
print(int(2.0 ** 62))

try:
    print(int(float("nan")))
except ValueError as e:
    print("nan:", e)
try:
    print(int(float("inf")))
except OverflowError as e:
    print("inf:", e)

# --- big integers: int() keeps the value, float() rounds it ---
for x in [2 ** 80, -(2 ** 80)]:
    print(int(x), float(x))

# --- Decimal truncates toward zero, exactly, and does not round first ---
from decimal import Decimal

for x in [Decimal("2.999"), Decimal("-2.999"), Decimal("1E+5"), Decimal("0")]:
    print(int(x), float(x))

# --- the non-numeric tags raise instead of answering ---
for bad in [None, [1], {"a": 1}]:
    try:
        int(bad)
    except TypeError as e:
        print("int TypeError:", e)
    try:
        float(bad)
    except TypeError as e:
        print("float TypeError:", e)

# --- a string element that will not parse reports the literal ---
try:
    print(int(["x"][0]))
except ValueError as e:
    print("badstr:", e)

# --- converted values are ordinary numbers downstream ---
s = ["12", 3]
print(int(s[0]) + 1)
print(float(s[0]) + 0.5)
print(int(v[1]) * 3, float(v[0]) / 2)
