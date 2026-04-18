# Regression: monomorphization for functions called with different scalar types.
#
# Before fix: def f(x): return x + 1 called as both f(5) and f(1.5) would
# get param_types merged to "mixed", forcing i64 representation and truncating
# the float case. Now we generate two specializations (f__i and f__d).

def add_one(x):
    return x + 1

print(add_one(5))       # expected: 6
print(add_one(1.5))     # expected: 2.5

# Multiple params, different types per call
def combine(a, b):
    return a + b * 2

print(combine(3, 4))          # expected: 11 (int)
print(combine(3.0, 4.0))      # expected: 11.0 (float)
print(combine(2, 3))          # expected: 8 (int)

# Single-param specialization with float and int call
def double(x):
    return x * 2

print(double(7))        # expected: 14
print(double(2.5))      # expected: 5.0
print(double(-3))       # expected: -6
print(double(-1.5))     # expected: -3.0

# Three specializations (int, float, bool) — bool merges with int
def triple(x):
    return x + x + x

print(triple(10))       # expected: 30
print(triple(1.5))      # expected: 4.5

# Recursive monomorphized function: f(x - 1) must resolve to the same spec
def count_down(n):
    if n <= 0:
        return 0
    return n + count_down(n - 1)

print(count_down(5))     # expected: 15 (int spec: 5+4+3+2+1)
print(count_down(3.5))   # expected: 8.0 (float spec: 3.5+2.5+1.5+0.5)

# Recursive float: fact-like
def accumulate(x):
    if x <= 1.0:
        return x
    return x + accumulate(x - 1.0)

print(accumulate(4.0))   # expected: 10.0 (4.0 + 3.0 + 2.0 + 1.0)
print(accumulate(2.5))   # expected: 4.0 (2.5 + 1.5)

