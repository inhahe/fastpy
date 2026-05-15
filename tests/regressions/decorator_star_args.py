# Regression: decorator pattern with *args forwarding
# Bug: func(*args) inside a decorator wrapper crashed because:
# 1. The decorated function (greet) used FV-ABI ({i32,i64} struct params)
#    but closure_call_list called it with raw i64 args — ABI mismatch.
# 2. _detect_string_params didn't detect string concat patterns for
#    params used as: "literal" + param, causing param type to default
#    to i64 instead of i8* (string pointer).
# 3. _emit_expr_value returned a raw FV-ABI function pointer instead of
#    the i64 wrapper when a function was used as a first-class value.
# Fix: Three-part fix:
#   a) _emit_expr_value: use i64 wrapper for FV-ABI functions used as values
#   b) _detect_string_params: properly detect string concat patterns
#   c) _get_or_emit_i64_wrapper: fall back to static_param_types for tags

# Case 1: Basic decorator with string arg
def decorator(func):
    def wrapper(*args):
        print("before")
        result = func(*args)
        print("after")
        return result
    return wrapper

def greet(name):
    print("Hello, " + name + "!")

decorated = decorator(greet)
decorated("World")

# Case 2: Decorator with integer arg
def double_func(func):
    def wrapper(*args):
        result = func(*args)
        return result
    return wrapper

def square(x):
    return x * x

wrapped_square = double_func(square)
print(wrapped_square(5))

# Case 3: Decorator with multiple args
def log_call(func):
    def wrapper(*args):
        result = func(*args)
        return result
    return wrapper

def add(a, b):
    return a + b

logged_add = log_call(add)
print(logged_add(3, 4))

# Case 4: Using @ syntax
@decorator
def say_hi(name):
    print("Hi, " + name + "!")

say_hi("Alice")

# Case 5: Chained decorators
def uppercase_result(func):
    def wrapper(*args):
        result = func(*args)
        return result
    return wrapper

@uppercase_result
@log_call
def get_greeting(name):
    return "hello " + name

result = get_greeting("Bob")
print(result)

# Case 6: *args with mixed types passed to print
def printer(func):
    def wrapper(*args):
        func(*args)
    return wrapper

def show(msg):
    print(msg)

p = printer(show)
p("test message")
