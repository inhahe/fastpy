# Regression test: realistic programs using the per-variable annotation system
# compile_flags:
#
# Tests unchecked_int/checked_int/Annotated in real algorithmic patterns,
# not just isolated arithmetic operations.

from typing import Annotated

class Unchecked:
    pass

class Checked:
    pass

def unchecked_int(x=0):
    return int(x)

def checked_int(x=0):
    return int(x)


# ── Program 1: sum of squares with unchecked accumulator ────────────
def sum_of_squares(n):
    total = unchecked_int(0)
    i = unchecked_int(1)
    while i <= n:
        total = total + i * i
        i = i + 1
    return total

print(sum_of_squares(10))   # 385
print(sum_of_squares(100))  # 338350
print(sum_of_squares(0))    # 0


# ── Program 2: fibonacci with checked arithmetic ────────────────────
def fibonacci(n):
    a = checked_int(0)
    b = checked_int(1)
    i = 2
    while i <= n:
        temp = a + b
        a = b
        b = temp
        i = i + 1
    return b

print(fibonacci(10))  # 55
print(fibonacci(20))  # 6765
print(fibonacci(30))  # 832040


# ── Program 3: dot product via Annotated parameter ──────────────────
def dot_product(xs, ys):
    result: Annotated[int, Unchecked] = 0
    i = 0
    while i < len(xs):
        result = result + xs[i] * ys[i]
        i = i + 1
    return result

print(dot_product([1, 2, 3], [4, 5, 6]))   # 32
print(dot_product([10, 20], [3, 4]))        # 110
print(dot_product([], []))                  # 0


# ── Program 4: power-of-two table with unchecked wrapping ───────────
def power_table(base, count):
    vals = []
    p = unchecked_int(1)
    i = 0
    while i < count:
        vals.append(p)
        p = p * base
        i = i + 1
    return vals

table = power_table(2, 10)
print(table)  # [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]


# ── Program 5: checked accumulator with error recovery ──────────────
def safe_sum(nums):
    total = checked_int(0)
    for n in nums:
        try:
            total = total + n
        except OverflowError:
            return -1   # signal overflow
    return total

print(safe_sum([100, 200, 300]))  # 600
print(safe_sum([1, 2, 3, 4, 5])) # 15


# ── Program 6: mixed modes in same function ─────────────────────────
def mixed_compute(n):
    fast_acc = unchecked_int(0)     # raw speed, no checks
    safe_acc = checked_int(0)       # overflow protection
    i = 1
    while i <= n:
        fast_acc = fast_acc + i
        safe_acc = safe_acc + i
        i = i + 1
    return fast_acc + safe_acc      # both contribute to result

print(mixed_compute(10))  # 55 + 55 = 110
print(mixed_compute(20))  # 210 + 210 = 420


# ── Program 7: Annotated function parameter in a loop ───────────────
def scale(val: Annotated[int, Unchecked], factor) -> int:
    return val * factor

total = 0
for i in range(1, 6):
    total = total + scale(i, 10)
print(total)  # 10+20+30+40+50 = 150


# ── Program 8: nested function calls with checked arithmetic ────────
def checked_square(n):
    v = checked_int(n)
    return v * v

def sum_of_checked_squares(limit):
    total = 0
    i = 1
    while i <= limit:
        total = total + checked_square(i)
        i = i + 1
    return total

print(sum_of_checked_squares(5))   # 1+4+9+16+25 = 55
print(sum_of_checked_squares(10))  # 385
