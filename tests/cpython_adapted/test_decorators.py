# Adapted from CPython Lib/test/test_decorators.py
# Tests decorator patterns

# Basic function decorator
def log_call(func):
    def wrapper(x):
        print("calling", func.__name__)
        result = func(x)
        print("result:", result)
        return result
    wrapper.__name__ = "wrapped_" + func.__name__
    return wrapper

@log_call
def double(x):
    return x * 2

@log_call
def negate(x):
    return -x

double(5)
negate(3)

# Decorator preserving behavior
def identity_decorator(func):
    def wrapper(x):
        return func(x)
    return wrapper

@identity_decorator
def square(x):
    return x * x

print(square(5))
print(square(-3))

# Counter decorator
call_counts = {}

def count_calls(func):
    call_counts[func.__name__] = 0
    def wrapper(x):
        call_counts[func.__name__] += 1
        return func(x)
    wrapper.__name__ = func.__name__
    return wrapper

@count_calls
def increment(x):
    return x + 1

@count_calls
def decrement(x):
    return x - 1

increment(1)
increment(2)
increment(3)
decrement(10)
print(call_counts["increment"])
print(call_counts["decrement"])

# Validation decorator
def validate_positive(func):
    def wrapper(x):
        if x < 0:
            print("error: negative input")
            return None
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

# Memoization decorator
def memoize(func):
    cache = {}
    def wrapper(n):
        if n not in cache:
            cache[n] = func(n)
        return cache[n]
    wrapper.__name__ = func.__name__
    wrapper.cache = cache
    return wrapper

@memoize
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

print(fib(10))
print(fib(20))
print(fib(30))
print(len(fib.cache))

# Class decorator (method wrapper)
class Timer:
    """Simulated timer decorator for methods."""
    def __init__(self, func):
        self.func = func
        self.call_count = 0

    def __call__(self, x):
        self.call_count += 1
        return self.func(x)

@Timer
def process(x):
    return x * x + 1

print(process(5))
print(process(3))
print(process.call_count)

# Stacked decorators
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

# Decorator with class
def add_repr(cls):
    def new_repr(self):
        return cls.__name__ + "(...)"
    cls.__repr__ = new_repr
    return cls

# Simple method decorator
def trace_method(method):
    def wrapper(self, x):
        print("  trace:", method.__name__, x)
        return method(self, x)
    return wrapper

class Calculator:
    def __init__(self):
        self.value = 0

    @trace_method
    def add(self, x):
        self.value += x
        return self.value

    @trace_method
    def multiply(self, x):
        self.value *= x
        return self.value

calc = Calculator()
print(calc.add(5))
print(calc.multiply(3))
print(calc.add(2))
