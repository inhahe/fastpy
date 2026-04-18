# Real-world patterns test — patterns from actual Python programs

# Real-world algorithm tests

# --- FizzBuzz ---
def fizzbuzz(n):
    results = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            results.append("FizzBuzz")
        elif i % 3 == 0:
            results.append("Fizz")
        elif i % 5 == 0:
            results.append("Buzz")
        else:
            results.append(i)
    return results

# Can't mix types in list yet — simplified version
def fizzbuzz_nums(n):
    results = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            results.append(-3)
        elif i % 3 == 0:
            results.append(-1)
        elif i % 5 == 0:
            results.append(-2)
        else:
            results.append(i)
    return results

print(f"fizzbuzz: {fizzbuzz_nums(15)}")

# --- Collatz sequence ---
def collatz(n):
    seq = [n]
    while n != 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        seq.append(n)
    return seq

print(f"collatz(6): {collatz(6)}")

# --- Power function ---
def power(base, exp):
    result = 1
    while exp > 0:
        if exp % 2 == 1:
            result *= base
        base *= base
        exp = exp // 2
    return result

print(f"2^10 = {power(2, 10)}")
print(f"3^5 = {power(3, 5)}")

# --- Sieve of Eratosthenes (compact) ---
def primes_up_to(n):
    sieve = []
    for i in range(n + 1):
        sieve.append(1)
    sieve[0] = 0
    sieve[1] = 0
    i = 2
    while i * i <= n:
        if sieve[i] == 1:
            j = i * i
            while j <= n:
                sieve[j] = 0
                j += i
        i += 1
    result = []
    for i in range(n + 1):
        if sieve[i] == 1:
            result.append(i)
    return result

print(f"primes: {primes_up_to(50)}")

# --- Simple class hierarchy ---
class Shape:
    def __init__(self, name):
        self.name = name
    def describe(self):
        return f"{self.name}: area={self.area()}"

class Circle(Shape):
    def __init__(self, r):
        self.name = "Circle"
        self.r = r
    def area(self):
        return 3 * self.r * self.r  # approximate pi as 3

class Square(Shape):
    def __init__(self, s):
        self.name = "Square"
        self.s = s
    def area(self):
        return self.s * self.s

shapes = [Circle(5), Square(4)]
for shape in shapes:
    print(shape.describe())

# --- Matrix multiply ---
def matrix_multiply(a, b):
    rows_a = len(a)
    cols_a = len(a[0])
    cols_b = len(b[0])
    result = []
    i = 0
    while i < rows_a:
        row = []
        j = 0
        while j < cols_b:
            total = 0
            k = 0
            while k < cols_a:
                total = total + a[i][k] * b[k][j]
                k = k + 1
            row.append(total)
            j = j + 1
        result.append(row)
        i = i + 1
    return result

m1 = [[1, 2], [3, 4]]
m2 = [[5, 6], [7, 8]]
product = matrix_multiply(m1, m2)
print(f"matrix: [{product[0]}, {product[1]}]")

# --- Pascal's triangle ---
def pascals_triangle(n):
    triangle = []
    i = 0
    while i < n:
        row = []
        j = 0
        while j <= i:
            if j == 0 or j == i:
                row.append(1)
            else:
                row.append(triangle[i - 1][j - 1] + triangle[i - 1][j])
            j = j + 1
        triangle.append(row)
        i = i + 1
    return triangle

pascal = pascals_triangle(6)
for row in pascal:
    print(row)
