# Regression test: per-variable integer overflow modes
# Tests unchecked_int(), checked_int(), and Annotated[int, Unchecked/Checked]
# compile_flags:

# ── Local shims (CPython compatibility) ──────────────────────────────
# Under CPython: Annotated is a no-op hint, constructors return plain int.
# Under the compiler: AST-level interception makes these work natively.
from typing import Annotated

class Unchecked:
    pass

class Checked:
    pass

def unchecked_int(x=0):
    return int(x)

def checked_int(x=0):
    return int(x)


# ── unchecked_int() constructor ──────────────────────────────────────
x = unchecked_int(42)
print(x)            # 42

x = x + 8
print(x)            # 50

x = x - 20
print(x)            # 30

x = x * 3
print(x)            # 90


# ── checked_int() constructor ────────────────────────────────────────
y = checked_int(10)
print(y)            # 10

y = y + 5
print(y)            # 15

y = y * 4
print(y)            # 60

y = y - 30
print(y)            # 30


# ── Annotated[int, Unchecked] ────────────────────────────────────────
a: Annotated[int, Unchecked] = 100
a = a + 50
print(a)            # 150

a = a * 2
print(a)            # 300

a = a - 100
print(a)            # 200


# ── Annotated[int, Checked] ─────────────────────────────────────────
b: Annotated[int, Checked] = 7
b = b + 3
print(b)            # 10

b = b * 5
print(b)            # 50

b = b - 25
print(b)            # 25


# ── Mixed: unchecked and checked in the same scope ───────────────────
u = unchecked_int(1000)
c = checked_int(1000)
u = u + 1
c = c + 1
print(u)            # 1001
print(c)            # 1001

# ── Power operator ───────────────────────────────────────────────────
p = unchecked_int(2)
p = p ** 10
print(p)            # 1024

q = checked_int(3)
q = q ** 5
print(q)            # 243


# ── Inside functions ─────────────────────────────────────────────────
def compute_unchecked():
    val = unchecked_int(5)
    val = val + val
    val = val * 3
    return val

def compute_checked():
    val = checked_int(5)
    val = val + val
    val = val * 3
    return val

print(compute_unchecked())  # 30
print(compute_checked())    # 30


# ── Function with Annotated parameter ────────────────────────────────
def add_unchecked(n: Annotated[int, Unchecked]) -> int:
    return n + 1

def add_checked(n: Annotated[int, Checked]) -> int:
    return n + 1

print(add_unchecked(99))    # 100
print(add_checked(99))      # 100


# ── Augmented assignment (+=, -=, *=) ────────────────────────────────
au = unchecked_int(10)
au += 5
print(au)           # 15
au -= 3
print(au)           # 12
au *= 4
print(au)           # 48

ac = checked_int(10)
ac += 5
print(ac)           # 15
ac -= 3
print(ac)           # 12
ac *= 4
print(ac)           # 48

aa: Annotated[int, Unchecked] = 20
aa += 30
print(aa)           # 50

ab: Annotated[int, Checked] = 20
ab += 30
print(ab)           # 50
