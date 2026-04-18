# Regression: monomorphization with keyword arguments and defaults
#
# Tests that specialization resolution uses AST arg nodes to infer types
# even when some args are passed as keywords.

def scale(value, factor=1):
    return value * factor

# Positional int, default int
print(scale(5))           # expected: 5

# Positional float, default int (still int for factor)
print(scale(3.0))         # expected: 3.0

# Both positional
print(scale(10, 2))       # expected: 20
print(scale(10.0, 2.0))   # expected: 20.0

# Keyword for factor
print(scale(4, factor=3))     # expected: 12
print(scale(2.5, factor=4.0)) # expected: 10.0


# Function with multiple specializations and cross-calls
def inner(x):
    return x * 2

def outer(y):
    return inner(y) + 1

print(outer(5))          # expected: 11 (outer__i -> inner__i: 5*2+1)
print(outer(2.5))        # expected: 6.0 (outer__d -> inner__d: 2.5*2+1.0)
