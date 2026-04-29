"""Test functools.partial implementation (positional args, int-typed)."""
from functools import partial

def power(base, exponent):
    result = 1
    i = 0
    while i < exponent:
        result *= base
        i += 1
    return result

# partial(power, 2) → fixes base=2
square = partial(power, 2)
print(square(10))  # 1024 (2^10)
print(square(5))   # 32 (2^5)

def add(a, b):
    return a + b

add5 = partial(add, 5)
print(add5(3))   # 8
print(add5(10))  # 15

def multiply(x, y):
    return x * y

double = partial(multiply, 2)
print(double(7))   # 14
print(double(25))  # 50

print("partial tests passed!")
