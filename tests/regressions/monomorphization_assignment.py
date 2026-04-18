# Regression: monomorphization + assignment target type inference
#
# When a monomorphized function's result is assigned to a variable, the
# variable's type tag must reflect the specialization actually called, not
# the alias (first spec) FuncInfo.

def f(x):
    return x + 1

x = f(5)
y = f(1.5)
print(x)         # expected: 6
print(y)         # expected: 2.5
print(x + 10)    # expected: 16
print(y + 1.0)   # expected: 3.5

def g(a, b):
    return a * b + 1

z1 = g(3, 4)
z2 = g(2.0, 3.0)
print(z1)        # expected: 13
print(z2)        # expected: 7.0

# Uses of monomorphized function in expressions
print(f(10) + f(20))      # expected: 32 (int)
print(f(1.5) + f(2.5))    # expected: 6.0 (float)
