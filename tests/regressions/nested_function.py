# Regression: nested functions with closure (read-only capture of outer variable)

# Read-only capture of outer variable
def make_adder(n):
    def add(x):
        return x + n
    return add

add5 = make_adder(5)
print(add5(3))          # 8
print(add5(10))         # 15

# Nested lambda capturing outer variable
def make_multiplier(factor):
    return lambda x: x * factor

double = make_multiplier(2)
triple = make_multiplier(3)
print(double(7))        # 14
print(triple(7))        # 21

# Multiple levels of capture
def outer(a):
    def middle(b):
        def inner(c):
            return a + b + c
        return inner
    return middle

f = outer(1)(2)
print(f(3))             # 6

# Capture of loop variable via default arg pattern
funcs = []
for i in range(3):
    funcs.append(lambda x, i=i: x + i)
print(funcs[0](10))     # 10
print(funcs[1](10))     # 11
print(funcs[2](10))     # 12
