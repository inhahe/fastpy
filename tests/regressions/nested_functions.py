# Regression: simple nested function definitions (no captured vars).
# Previously failed with "Unsupported function call" because inner
# funcs weren't hoisted to module level.

def outer():
    def inner(x):
        return x + 1
    return inner(5)

print(outer())

def solver(xs):
    def double(x):
        return x * 2
    total = 0
    for x in xs:
        total = total + double(x)
    return total

print(solver([1, 2, 3, 4, 5]))

def helpers():
    def add(a, b):
        return a + b
    def sub(a, b):
        return a - b
    return add(10, 5) - sub(20, 7)

print(helpers())

# Nested with different types
def mixed():
    def stringify(n):
        return str(n) + "!"
    return stringify(42)

print(mixed())
