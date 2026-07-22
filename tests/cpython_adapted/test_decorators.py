# Adapted from CPython Lib/test/test_decorators.py
# Tests decorator patterns (without func.__name__)

# Basic function decorator
def log_call(func):
    def wrapper(x):
        print("calling")
        result = func(x)
        print("result:", result)
        return result
    return wrapper

@log_call
def double(x):
    return x * 2

@log_call
def negate(x):
    return -x

double(5)
negate(3)

# Identity decorator
def identity_decorator(func):
    def wrapper(x):
        return func(x)
    return wrapper

@identity_decorator
def square(x):
    return x * x

print(square(5))
print(square(-3))

# Counter decorator using list (mutable capture)
increment_count = [0]
decrement_count = [0]

def count_inc(func):
    def wrapper(x):
        increment_count[0] += 1
        return func(x)
    return wrapper

def count_dec(func):
    def wrapper(x):
        decrement_count[0] += 1
        return func(x)
    return wrapper

@count_inc
def increment(x):
    return x + 1

@count_dec
def decrement(x):
    return x - 1

increment(1)
increment(2)
increment(3)
decrement(10)
print(increment_count[0])
print(decrement_count[0])

# Validation decorator
def validate_positive(func):
    def wrapper(x):
        if x < 0:
            print("error: negative input")
            return -1
        return func(x)
    return wrapper

@validate_positive
def sqrt_int(x):
    result = 0
    while (result + 1) * (result + 1) <= x:
        result += 1
    return result

print(sqrt_int(16))
print(sqrt_int(25))
sqrt_int(-1)
print(sqrt_int(0))

# Stacked decorators with string returns
def add_prefix(func):
    def wrapper(x):
        return ">> " + func(x)
    return wrapper

def add_suffix(func):
    def wrapper(x):
        return func(x) + " <<"
    return wrapper

@add_prefix
@add_suffix
def greet(name):
    return "Hello, " + name

print(greet("World"))
print(greet("Python"))

# Decorator that doubles the result
def double_result(func):
    def wrapper(x):
        return func(x) * 2
    return wrapper

@double_result
def add_ten(x):
    return x + 10

print(add_ten(5))    # (5+10)*2 = 30
print(add_ten(0))    # (0+10)*2 = 20
print(add_ten(-5))   # (-5+10)*2 = 10

# Chained decorators
@double_result
@identity_decorator
def triple(x):
    return x * 3

print(triple(4))    # (4*3)*2 = 24
print(triple(7))    # (7*3)*2 = 42

# Closure-based decorator with state
def make_adder(n):
    def decorator(func):
        def wrapper(x):
            return func(x) + n
        return wrapper
    return decorator

@make_adder(100)
def get_value(x):
    return x

print(get_value(5))    # 5+100 = 105
print(get_value(42))   # 42+100 = 142
