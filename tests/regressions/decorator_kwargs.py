# Regression: decorator pattern with **kwargs forwarding
# Note: kwargs-to-positional mapping uses dict insertion order,
# so kwargs must be passed in the same order as the function's params.

# Case 1: Simple **kwargs in closure — string return
def wrap(func):
    def wrapper(**kwargs):
        return func(**kwargs)
    return wrapper

def hello(name="World"):
    return "Hello, " + name + "!"

w = wrap(hello)
print(w(name="Alice"))

# Case 2: **kwargs with int return
def wrap2(func):
    def wrapper(**kwargs):
        return func(**kwargs)
    return wrapper

def add(a=0, b=0):
    return a + b

w2 = wrap2(add)
print(w2(a=3, b=4))

# Case 3: Using @ syntax with kwargs in param order
@wrap
def greet(greeting="Hi", name="World"):
    return greeting + ", " + name + "!"

print(greet(greeting="Hello", name="Bob"))
