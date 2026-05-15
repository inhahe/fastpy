# Regression: two outer functions define inner functions with the same name
# Bug: hoisted inner functions share a flat _user_functions key (the simple
# name), so the second "helper" overwrites the first and both outers call
# the same body.

def outer1():
    def helper():
        return 1
    return helper()

def outer2():
    def helper():
        return 2
    return helper()

print(outer1())  # 1
print(outer2())  # 2

# With arguments
def make_greeter():
    def greet(name):
        return "Hello " + name
    return greet("World")

def make_farewell():
    def greet(name):
        return "Bye " + name
    return greet("World")

print(make_greeter())   # Hello World
print(make_farewell())  # Bye World
