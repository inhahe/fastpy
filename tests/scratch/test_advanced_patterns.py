# Advanced patterns

# 1. Closure with mutable state
def make_counter(start=0):
    count = start
    def increment():
        nonlocal count
        count = count + 1
        return count
    return increment

c = make_counter(10)
print(c())
print(c())
print(c())

# 2. Exception handling chain
def safe_div(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return float('inf')

print(safe_div(10, 3))
print(safe_div(10, 0))

# 3. Multiple except clauses
def parse_value(s):
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s

print(parse_value("42"))
print(parse_value("3.14"))
print(parse_value("hello"))

# 4. Recursive function
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

print(fibonacci(10))

# 5. Higher-order functions
def apply_twice(f, x):
    return f(f(x))

def double(x):
    return x * 2

print(apply_twice(double, 3))

# 6. Star args
def sum_all(*args):
    total = 0
    for a in args:
        total = total + a
    return total

print(sum_all(1, 2, 3, 4, 5))

# 7. Keyword arguments
def make_greeting(name, greeting="Hello", punctuation="!"):
    return greeting + " " + name + punctuation

print(make_greeting("Alice"))
print(make_greeting("Bob", greeting="Hi"))
print(make_greeting("Charlie", punctuation="."))
