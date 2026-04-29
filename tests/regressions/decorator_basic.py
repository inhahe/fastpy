# Regression: decorator application
# Tests @identity (returns same function) and @wrapper (returns closure)

# 1. Identity decorator — returns the function unchanged
def identity(f):
    return f

@identity
def greet(name):
    return "hello " + name

print(greet("world"))  # hello world

# 2. Wrapping decorator — returns a new closure
def double_result(fn):
    def wrapper(x):
        return fn(x) * 2
    return wrapper

@double_result
def square(x):
    return x * x

print(square(3))  # 18
print(square(5))  # 50

# 3. Identity decorator with two-arg numeric function
@identity
def add(a, b):
    return a + b

print(add(3, 4))   # 7
print(add(10, 20)) # 30

# 4. Wrapping decorator with zero-arg function
def double0(fn):
    def w():
        return fn() * 2
    return w

@double0
def get_five():
    return 5

print(get_five())  # 10
