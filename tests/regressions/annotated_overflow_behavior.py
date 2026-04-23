# Regression test: per-variable overflow behavior verification
# Tests that unchecked wraps and checked raises OverflowError.
# compile_flags:
#
# Under CPython: wrapper classes simulate i64 overflow semantics so
# the differential output matches the compiler's native behavior.
# Under the compiler: wrapper classes are compiled but never used
# (unchecked_int/checked_int calls are intercepted at AST level).

from typing import Annotated

# ── CPython shim: i64-accurate wrapper classes ───────────────────────
# These classes are DEAD CODE under the compiler — the compiler
# intercepts unchecked_int()/checked_int() at the AST level and
# stores raw i64 values instead.

_I64_MAX = 9223372036854775807

class _WrapI64:
    """Simulates unchecked i64 wrapping arithmetic under CPython."""
    def __init__(self, v):
        v = int(v)
        # Two's complement wrapping: subtract 2*MAX+2 (= 2^64) in i64-safe steps
        while v > _I64_MAX:
            v = v - _I64_MAX
            v = v - _I64_MAX
            v = v - 2
        while v < -_I64_MAX - 1:
            v = v + _I64_MAX
            v = v + _I64_MAX
            v = v + 2
        self.v = v

    def __add__(self, other):
        ov = other.v if isinstance(other, _WrapI64) else int(other)
        return _WrapI64(self.v + ov)

    def __sub__(self, other):
        ov = other.v if isinstance(other, _WrapI64) else int(other)
        return _WrapI64(self.v - ov)

    def __mul__(self, other):
        ov = other.v if isinstance(other, _WrapI64) else int(other)
        return _WrapI64(self.v * ov)

    def __pow__(self, other):
        ov = other.v if isinstance(other, _WrapI64) else int(other)
        return _WrapI64(self.v ** ov)

    def __str__(self):
        return str(self.v)


class _CheckI64:
    """Simulates checked i64 arithmetic under CPython (OverflowError)."""
    def __init__(self, v):
        v = int(v)
        if v > _I64_MAX or v < -_I64_MAX - 1:
            raise OverflowError("integer overflow")
        self.v = v

    def __add__(self, other):
        ov = other.v if isinstance(other, _CheckI64) else int(other)
        return _CheckI64(self.v + ov)

    def __sub__(self, other):
        ov = other.v if isinstance(other, _CheckI64) else int(other)
        return _CheckI64(self.v - ov)

    def __mul__(self, other):
        ov = other.v if isinstance(other, _CheckI64) else int(other)
        return _CheckI64(self.v * ov)

    def __str__(self):
        return str(self.v)


def unchecked_int(x=0):
    return _WrapI64(x)

def checked_int(x=0):
    return _CheckI64(x)

class Unchecked:
    pass

class Checked:
    pass


# ════════════════════════════════════════════════════════════════════
# Overflow tests — these exercise the ACTUAL behavioral differences
# between the three integer modes.
# ════════════════════════════════════════════════════════════════════

# ── Unchecked: MAX + 1 wraps to MIN ─────────────────────────────────
x = unchecked_int(9223372036854775807)
x = x + 1
print(x)                # -9223372036854775808

# ── Unchecked: MAX + MAX wraps ───────────────────────────────────────
a = unchecked_int(9223372036854775807)
b = unchecked_int(9223372036854775807)
c = a + b
print(c)                # -2

# ── Unchecked: MAX * 2 wraps ────────────────────────────────────────
m = unchecked_int(9223372036854775807)
m = m * 2
print(m)                # -2

# ── Unchecked: subtraction underflow wraps ───────────────────────────
s = unchecked_int(-9223372036854775807)
s = s - 2
print(s)                # 9223372036854775807

# ── Checked: addition overflow → OverflowError ──────────────────────
y = checked_int(9223372036854775807)
try:
    y = y + 1
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught

# ── Checked: multiplication overflow → OverflowError ────────────────
z = checked_int(9223372036854775807)
try:
    z = z * 2
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught

# ── Checked: subtraction underflow → OverflowError ──────────────────
w = checked_int(-9223372036854775807)
try:
    w = w - 2
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught

# ── Checked: normal range works fine ─────────────────────────────────
ok = checked_int(1000000)
ok = ok + 999000
print(ok)               # 1999000

# ── Unchecked augmented assignment wraps ─────────────────────────────
au = unchecked_int(9223372036854775807)
au += 10
print(au)               # -9223372036854775799

# ── Checked augmented assignment overflows ───────────────────────────
ac = checked_int(9223372036854775807)
try:
    ac += 1
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught
