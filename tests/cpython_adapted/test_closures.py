# Adapted from CPython Lib/test/test_scope.py (closure portions)
# Tests closures and nonlocal variables

# Basic closure
def make_adder(n):
    def add(x):
        return x + n
    return add

add5 = make_adder(5)
add10 = make_adder(10)
print(add5(3))
print(add10(3))
print(add5(0))
print(add10(0))

# Closure over mutable state (via list)
def make_counter():
    count = [0]
    def increment():
        count[0] = count[0] + 1
        return count[0]
    def get():
        return count[0]
    return increment, get

inc, get = make_counter()
print(get())
print(inc())
print(inc())
print(inc())
print(get())

# Multiple closures from same factory
def multiplier(factor):
    def multiply(x):
        return x * factor
    return multiply

double = multiplier(2)
triple = multiplier(3)
quadruple = multiplier(4)
print(double(5))
print(triple(5))
print(quadruple(5))

# Closure in loop with default argument
functions = []
for i in range(5):
    def f(x, i=i):
        return x * i
    functions.append(f)

for fn in functions:
    print(fn(10))

# Nested closures (2 levels)
def outer(a):
    def middle(b):
        def inner(c):
            return a + b + c
        return inner(1)
    return middle

print(outer(10)(20))
print(outer(100)(200))

# Closure accessing multiple free variables
def make_linear(m, b):
    def f(x):
        return m * x + b
    return f

line1 = make_linear(2, 3)
line2 = make_linear(-1, 10)
print(line1(0))
print(line1(5))
print(line2(0))
print(line2(5))

# Closure with conditional
def make_filter(threshold):
    def check(x):
        if x > threshold:
            return True
        return False
    return check

above5 = make_filter(5)
above10 = make_filter(10)
data = [1, 3, 5, 7, 9, 11, 13, 15]
print([x for x in data if above5(x)])
print([x for x in data if above10(x)])

# Factory pattern
def make_accumulator():
    total = [0]
    def add(n):
        total[0] = total[0] + n
        return total[0]
    return add

acc = make_accumulator()
print(acc(5))
print(acc(10))
print(acc(3))
print(acc(-8))

# Closure returning closure
def compose(f, g):
    def composed(x):
        return f(g(x))
    return composed

def inc(x):
    return x + 1

def dbl(x):
    return x * 2

inc_then_dbl = compose(dbl, inc)
dbl_then_inc = compose(inc, dbl)
print(inc_then_dbl(3))  # (3+1)*2 = 8
print(dbl_then_inc(3))  # 3*2+1 = 7
print(inc_then_dbl(0))  # (0+1)*2 = 2
print(dbl_then_inc(0))  # 0*2+1 = 1
