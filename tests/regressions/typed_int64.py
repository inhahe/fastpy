# Regression test for --typed --int64 raw integer arithmetic
# compile_flags: --typed --int64
#
# When both flags are active, annotated int operations should use raw
# LLVM add/sub/mul/pow with no overflow-check runtime calls.

# Test: basic arithmetic (add, sub, mul)
def add(a: int, b: int) -> int:
    return a + b

def sub(a: int, b: int) -> int:
    return a - b

def mul(a: int, b: int) -> int:
    return a * b

print(add(100, 200))    # 300
print(sub(50, 30))      # 20
print(mul(7, 8))        # 56
print(add(-10, 10))     # 0
print(sub(3, 10))       # -7
print(mul(-3, 4))       # -12

# Test: power
def power(base: int, exp: int) -> int:
    return base ** exp

print(power(2, 10))     # 1024
print(power(3, 5))      # 243
print(power(5, 0))      # 1
print(power(7, 1))      # 7
print(power(-2, 3))     # -8
print(power(-2, 4))     # 16

# Test: compound expressions
def compound(a: int, b: int) -> int:
    return (a + b) * (a - b)

print(compound(10, 3))  # (13) * (7) = 91

# Test: annotated locals with arithmetic
def local_math() -> int:
    x: int = 100
    y: int = 37
    s: int = x + y
    d: int = x - y
    p: int = x * y
    return s + d + p

print(local_math())  # 137 + 63 + 3700 = 3900

# Test: loop accumulator
def factorial(n: int) -> int:
    result: int = 1
    i: int = 2
    while i <= n:
        result = result * i
        i = i + 1
    return result

print(factorial(10))  # 3628800
print(factorial(1))   # 1
print(factorial(0))   # 1

# Test: nested function calls
def square(x: int) -> int:
    return x * x

def sum_of_squares(a: int, b: int) -> int:
    return square(a) + square(b)

print(sum_of_squares(3, 4))  # 9 + 16 = 25

# Test: mixed typed/untyped still works
def untyped_add(a, b):
    return a + b

print(untyped_add(10, 20))  # 30

# Test: floor division and modulo (these already use raw LLVM ops)
def divmod_test(a: int, b: int) -> int:
    return (a // b) + (a % b)

print(divmod_test(17, 5))    # 3 + 2 = 5
print(divmod_test(-17, 5))   # -4 + 3 = -1
print(divmod_test(17, -5))   # -4 + -3 = -7

# Test: bitwise ops (already raw LLVM)
def bitwise(a: int, b: int) -> int:
    return (a & b) | (a ^ b)

print(bitwise(0xFF, 0x0F))  # (0x0F) | (0xF0) = 0xFF = 255
