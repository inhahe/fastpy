# Functions test program
# Tests def, return, default args, *args, **kwargs, closures, recursion, lambda

def add(a, b):
    return a + b

print(add(3, 4))

# Default arguments
def greet(name, greeting="Hello"):
    return f"{greeting}, {name}!"

print(greet("World"))
print(greet("World", "Hi"))

# Multiple return values
def divmod_custom(a, b):
    return a // b, a % b

q, r = divmod_custom(17, 5)
print(f"17 / 5 = {q} remainder {r}")

# Recursion
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

for i in range(8):
    print(f"{i}! = {factorial(i)}")

# Closure
def make_counter(start=0):
    count = start
    def increment():
        nonlocal count
        count += 1
        return count
    return increment

counter = make_counter(10)
print(counter())
print(counter())
print(counter())

# Lambda
square = lambda x: x * x
print([square(i) for i in range(6)])

# *args
def sum_all(*args):
    return sum(args)

print(sum_all(1, 2, 3, 4, 5))

# **kwargs
def describe(**kwargs):
    for key in sorted(kwargs):
        print(f"  {key}: {kwargs[key]}")

describe(name="Alice", age=30, city="NYC")

# Higher-order function
def apply_twice(f, x):
    return f(f(x))

print(apply_twice(lambda x: x + 1, 5))
print(apply_twice(lambda x: x * 2, 3))
