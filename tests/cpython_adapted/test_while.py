# Adapted from CPython tests for while loops
# Tests while loop semantics

# Basic while
i = 0
while i < 5:
    print(i)
    i += 1

# While with break
i = 0
while True:
    if i >= 5:
        break
    print(i, end=" ")
    i += 1
print()

# While with continue
i = 0
while i < 10:
    i += 1
    if i % 2 == 0:
        continue
    print(i, end=" ")
print()

# While-else (no break)
i = 0
while i < 5:
    i += 1
else:
    print("completed", i)

# While-else (with break)
i = 0
while i < 10:
    if i == 5:
        break
    i += 1
else:
    print("this should not print")
print("broke at", i)

# Countdown
n = 10
while n > 0:
    print(n, end=" ")
    n -= 1
print()

# Accumulator
total = 0
i = 1
while i <= 100:
    total += i
    i += 1
print(total)

# Collatz sequence
def collatz_length(n):
    steps = 0
    while n != 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        steps += 1
    return steps

print(collatz_length(1))
print(collatz_length(2))
print(collatz_length(7))
print(collatz_length(27))

# Newton's method (sqrt)
def sqrt_approx(n):
    guess = n / 2.0
    i = 0
    while i < 20:
        guess = (guess + n / guess) / 2.0
        i += 1
    return guess

print(round(sqrt_approx(4.0), 6))
print(round(sqrt_approx(9.0), 6))
print(round(sqrt_approx(2.0), 6))

# While consuming a list
items = [1, 2, 3, 4, 5]
result = []
while len(items) > 0:
    result.append(items.pop())
print(result)

# Nested while
i = 1
while i <= 3:
    j = 1
    while j <= 3:
        print(i * j, end=" ")
        j += 1
    print()
    i += 1

# While with complex condition
a = 10
b = 1
while a > 0 and b < 100:
    a -= 1
    b *= 2
print(a, b)

# GCD via while
def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a

print(gcd(48, 18))
print(gcd(100, 75))
print(gcd(17, 13))
