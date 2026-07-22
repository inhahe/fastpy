# Regression: closure decorator passing string args through captured function
# Previously, closure params defaulted to INT and string args were
# treated as pointer values.

def uppercase_decorator(func):
    def wrapper(text):
        return func(text.upper())
    return wrapper

@uppercase_decorator
def greet(name):
    return f"Hello, {name}!"

print(greet("alice"))
print(greet("bob"))
