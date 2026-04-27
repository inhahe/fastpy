# Regression test: 32-bit per-variable integer overflow modes
# Tests unchecked_int32(), checked_int32(), Annotated[int, Unchecked32/Checked32]
# compile_flags:

from typing import Annotated

# ── CPython shim: 32-bit wrapper classes ─────────────────────────────
# Dead code under the compiler (constructor calls intercepted at AST level).

_I32_MAX = 2147483647

class _WrapI32:
    """Simulates unchecked i32 wrapping arithmetic under CPython."""
    def __init__(self, v):
        v = int(v)
        while v > _I32_MAX:
            v = v - _I32_MAX - _I32_MAX - 2
        while v < -_I32_MAX - 1:
            v = v + _I32_MAX + _I32_MAX + 2
        self.v = v
    def __add__(self, other):
        ov = other.v if isinstance(other, _WrapI32) else int(other)
        return _WrapI32(self.v + ov)
    def __sub__(self, other):
        ov = other.v if isinstance(other, _WrapI32) else int(other)
        return _WrapI32(self.v - ov)
    def __mul__(self, other):
        ov = other.v if isinstance(other, _WrapI32) else int(other)
        return _WrapI32(self.v * ov)
    def __pow__(self, other):
        ov = other.v if isinstance(other, _WrapI32) else int(other)
        return _WrapI32(self.v ** ov)
    def __str__(self):
        return str(self.v)

class _CheckI32:
    """Simulates checked i32 arithmetic under CPython (OverflowError)."""
    def __init__(self, v):
        v = int(v)
        if v > _I32_MAX or v < -_I32_MAX - 1:
            raise OverflowError("integer overflow (i32)")
        self.v = v
    def __add__(self, other):
        ov = other.v if isinstance(other, _CheckI32) else int(other)
        return _CheckI32(self.v + ov)
    def __sub__(self, other):
        ov = other.v if isinstance(other, _CheckI32) else int(other)
        return _CheckI32(self.v - ov)
    def __mul__(self, other):
        ov = other.v if isinstance(other, _CheckI32) else int(other)
        return _CheckI32(self.v * ov)
    def __str__(self):
        return str(self.v)

def unchecked_int32(x=0):
    return _WrapI32(x)
def checked_int32(x=0):
    return _CheckI32(x)

class Unchecked32:
    pass
class Checked32:
    pass


# ═════════════════════════════════════════════════════════════════════
# Basic happy-path arithmetic
# ═══════════════════════════════════════════════════���═════════════════

# ── unchecked_int32() constructor ────────────────────────────────────
x = unchecked_int32(100)
print(x)            # 100
x = x + 50
print(x)            # 150
x = x - 30
print(x)            # 120
x = x * 3
print(x)            # 360

# ── checked_int32() constructor ──────────────────────────────────────
y = checked_int32(200)
print(y)            # 200
y = y + 100
print(y)            # 300
y = y - 50
print(y)            # 250
y = y * 2
print(y)            # 500

# ── Annotated[int, Unchecked32] ──────────────────────────────────────
a: Annotated[int, Unchecked32] = 42
a = a + 8
print(a)            # 50
a = a * 10
print(a)            # 500

# ── Annotated[int, Checked32] ───────────────────────────────────────
b: Annotated[int, Checked32] = 42
b = b + 8
print(b)            # 50
b = b * 10
print(b)            # 500

# ── Augmented assignment ─────────────────────────────────────────────
au = unchecked_int32(10)
au += 5
print(au)           # 15
au -= 3
print(au)           # 12
au *= 4
print(au)           # 48

ac = checked_int32(10)
ac += 5
print(ac)           # 15
ac -= 3
print(ac)           # 12
ac *= 4
print(ac)           # 48


# ═════════════════════════════════════════════════════════════════════
# Overflow behavior — 32-bit boundary (2^31 - 1 = 2147483647)
# ═════════════════════════════════════════════════════════════════════

# ── Unchecked: MAX + 1 wraps to MIN ─────────────────────────────────
ux = unchecked_int32(2147483647)
ux = ux + 1
print(ux)           # -2147483648

# ── Unchecked: MAX + MAX = -2 ───────────────────────────────────────
ua = unchecked_int32(2147483647)
ub = unchecked_int32(2147483647)
uc = ua + ub
print(uc)           # -2

# ── Unchecked: MAX * 2 wraps ────────────────────────────────────────
um = unchecked_int32(2147483647)
um = um * 2
print(um)           # -2

# ── Unchecked: subtraction underflow wraps ───────────────────────────
us = unchecked_int32(-2147483647)
us = us - 2
print(us)           # 2147483647

# ── Checked: addition overflow → OverflowError ──────────────────────
cy = checked_int32(2147483647)
try:
    cy = cy + 1
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught

# ── Checked: multiplication overflow → OverflowError ────────────────
cz = checked_int32(2147483647)
try:
    cz = cz * 2
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught

# ── Checked: subtraction underflow → OverflowError ──────────────────
cw = checked_int32(-2147483647)
try:
    cw = cw - 2
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught

# ── Checked: normal range fine ───────────────────────────────────────
cok = checked_int32(1000000)
cok = cok + 999000
print(cok)          # 1999000

# ── Augmented overflow ───────────────────────────────────────────────
auo = unchecked_int32(2147483647)
auo += 10
print(auo)          # -2147483639

aco = checked_int32(2147483647)
try:
    aco += 1
    print("no overflow")
except OverflowError:
    print("overflow caught")    # overflow caught


# ═════════════════════════════════════════════════════════════════════
# Inside functions
# ═════════════════════════════════════════════════════════════════════

def compute_unchecked32():
    val = unchecked_int32(5)
    val = val + val
    val = val * 3
    return val

def compute_checked32():
    val = checked_int32(5)
    val = val + val
    val = val * 3
    return val

print(compute_unchecked32())  # 30
print(compute_checked32())    # 30


# ── Function with Annotated parameter ────────────────────────────────
def add_unchecked32(n: Annotated[int, Unchecked32]) -> int:
    return n + 1

def add_checked32(n: Annotated[int, Checked32]) -> int:
    return n + 1

print(add_unchecked32(99))    # 100
print(add_checked32(99))      # 100


# ── Power operator ───────────────────────────────────────────────────
p = unchecked_int32(2)
p = p ** 10
print(p)            # 1024
