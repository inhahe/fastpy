# Advanced features test program
# Tests closures, higher-order functions, operator overloading, BigInt,
# mutable state, complex class hierarchies, exception handling

# --- Closures ---
def make_multiplier(factor):
    def multiply(x):
        return x * factor
    return multiply

double = make_multiplier(2)
triple = make_multiplier(3)
print(f"double(5) = {double(5)}")
print(f"triple(5) = {triple(5)}")

# Mutable closure
def accumulator(initial=0):
    total = initial
    def add(n):
        nonlocal total
        total += n
        return total
    return add

acc = accumulator()
print(f"acc(10) = {acc(10)}")
print(f"acc(20) = {acc(20)}")
print(f"acc(5) = {acc(5)}")

# --- Higher-order functions ---
squares = [x * x for x in [1, 2, 3, 4, 5]]
print(f"squares: {squares}")

# --- Operator overloading ---
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def __repr__(self):
        return f"Vector({self.x}, {self.y})"

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def length_squared(self):
        return self.x * self.x + self.y * self.y

v1 = Vector(1, 2)
v2 = Vector(3, 4)
v3 = v1 + v2
print(f"v1 + v2 = {v3}")
print(f"|v2|^2 = {v2.length_squared()}")
print(f"v1 == v1? {v1 == v1}")
print(f"v1 == v2? {v1 == v2}")

# --- BigInt ---
print(f"2^64 = {2 ** 64}")
print(f"10^30 = {10 ** 30}")
print(f"2^100 + 1 = {2 ** 100 + 1}")

# --- Complex control flow ---
def fizzbuzz(n):
    result = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            result.append(-3)
        elif i % 3 == 0:
            result.append(-1)
        elif i % 5 == 0:
            result.append(-2)
        else:
            result.append(i)
    return result

fb = fizzbuzz(20)
print(f"fizzbuzz: {fb}")

# --- Exception handling ---
def safe_sqrt(x):
    if x < 0:
        raise ValueError("negative")
    result = 1.0
    for i in range(20):
        result = (result + x / result) / 2.0
    return result

try:
    result = safe_sqrt(25.0)
    print(f"sqrt(25) = {result}")
except ValueError as e:
    print(f"error: {e}")

try:
    result = safe_sqrt(-1.0)
    print(f"sqrt(-1) = {result}")
except ValueError as e:
    print(f"error: {e}")

# --- Sorting and filtering ---
nums = [5, 2, 8, 1, 9, 3, 7, 4, 6]
print(f"sorted: {sorted(nums)}")
evens = [x for x in nums if x % 2 == 0]
print(f"evens: {sorted(evens)}")

# --- Dict operations ---
inventory = {"apples": 5, "bananas": 3, "cherries": 12}
total = 0
for key in sorted(inventory.keys()):
    total += 1
print(f"items: {total}")

# --- String operations ---
words = "hello world foo bar"
parts = words.split()
upper_parts = []
for w in parts:
    upper_parts.append(w)
result = "-".join(upper_parts)
print(f"joined: {result}")
