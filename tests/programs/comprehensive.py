# Comprehensive test program — exercises many features together

# --- List methods ---
nums = [5, 3, 8, 1, 9, 2, 7]
nums.sort()
print(f"sorted in place: {nums}")
nums.reverse()
print(f"reversed: {nums}")

a = [1, 2, 3]
b = [4, 5, 6]
a.extend(b)
print(f"extended: {a}")

# --- String methods ---
text = "Hello, World! Hello, Python!"
print(f"find World: {text.find('World')}")
print(f"find xyz: {text.find('xyz')}")
print(f"count Hello: {text.count('Hello')}")

# --- Bool/float conversion ---
print(f"bool(0): {bool(0)}")
print(f"bool(1): {bool(1)}")
print(f"float(42): {float(42)}")

# --- Simple class ---
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def magnitude_sq(self):
        return self.x * self.x + self.y * self.y
    def __repr__(self):
        return f"Point({self.x}, {self.y})"

p = Point(3, 4)
print(f"point: {p}, mag_sq: {p.magnitude_sq()}")

# --- Fibonacci with memoization (using list) ---
def fib_list(n):
    fibs = [0, 1]
    for i in range(2, n + 1):
        fibs.append(fibs[i - 1] + fibs[i - 2])
    return fibs

result = fib_list(10)
print(f"fib(10): {result}")

# --- String processing ---
csv_line = "Alice,30,NYC"
parts = csv_line.split()
print(f"csv parts: {parts}")

# --- Nested comprehension with filter ---
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
flat_even = [x for row in matrix for x in row if x % 2 == 0]
print(f"flat even: {flat_even}")

# --- Exception handling ---
def safe_divide(a, b):
    if b == 0:
        raise ValueError("cannot divide by zero")
    return a / b

try:
    result = safe_divide(10, 2)
    print(f"10/2 = {result}")
except ValueError as e:
    print(f"error: {e}")

try:
    result = safe_divide(10, 0)
    print(f"10/0 = {result}")
except ValueError as e:
    print(f"error: {e}")

# --- Global accumulator ---
total = 0
def accumulate(n):
    global total
    total += n
    return total

for i in range(1, 6):
    accumulate(i)
print(f"total: {total}")

# --- Multiple assignment ---
x = y = z = 0
x += 1
y += 2
z += 3
print(f"x={x}, y={y}, z={z}")
