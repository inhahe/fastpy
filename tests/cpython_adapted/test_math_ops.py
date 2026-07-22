# Adapted from CPython Lib/test/test_math.py
# Tests mathematical operations (without importing math module)

# Basic arithmetic identities
print(0 + 0)
print(1 * 1)
print(0 * 100)
print(100 * 0)
print(1 + (-1))

# Integer division
print(7 // 3)
print(7 // -3)
print(-7 // 3)
print(-7 // -3)
print(10 // 10)
print(0 // 5)

# Modulo
print(7 % 3)
print(7 % -3)
print(-7 % 3)
print(-7 % -3)
print(10 % 10)
print(0 % 5)

# Powers
print(2 ** 0)
print(2 ** 1)
print(2 ** 10)
print(2 ** 20)
print(3 ** 3)
print(10 ** 6)
print((-2) ** 3)
print((-2) ** 4)

# Float operations
print(round(1.0 / 3.0, 10))
print(round(2.0 / 3.0, 10))
print(round(22.0 / 7.0, 10))

# Square root via Newton's method
def sqrt(n):
    if n < 0:
        return -1.0
    if n == 0:
        return 0.0
    x = n / 2.0
    for i in range(50):
        x = (x + n / x) / 2.0
    return x

print(round(sqrt(0), 6))
print(round(sqrt(1), 6))
print(round(sqrt(4), 6))
print(round(sqrt(9), 6))
print(round(sqrt(16), 6))
print(round(sqrt(2), 6))
print(round(sqrt(100), 6))

# GCD
def gcd(a, b):
    while b:
        a, b = b, a % b
    return a

print(gcd(12, 8))
print(gcd(48, 18))
print(gcd(100, 75))
print(gcd(17, 13))
print(gcd(0, 5))
print(gcd(5, 0))
print(gcd(1, 1))

# LCM
def lcm(a, b):
    if a == 0 or b == 0:
        return 0
    return abs(a * b) // gcd(a, b)

print(lcm(4, 6))
print(lcm(12, 8))
print(lcm(7, 5))
print(lcm(0, 5))

# Factorial
def factorial(n):
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result

print(factorial(0))
print(factorial(1))
print(factorial(5))
print(factorial(10))
print(factorial(12))

# Fibonacci
def fib(n):
    a, b = 0, 1
    for i in range(n):
        a, b = b, a + b
    return a

for i in range(15):
    print(fib(i), end=" ")
print()

# Is prime
def is_prime(n):
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True

primes = [n for n in range(50) if is_prime(n)]
print(primes)

# Floor/ceiling via integer arithmetic
def floor(x):
    n = int(x)
    if x < 0 and x != n:
        return n - 1
    return n

def ceil(x):
    n = int(x)
    if x > 0 and x != n:
        return n + 1
    return n

print(floor(3.7))
print(floor(-3.7))
print(floor(3.0))
print(ceil(3.2))
print(ceil(-3.7))
print(ceil(3.0))
