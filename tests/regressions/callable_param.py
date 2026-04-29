"""Callable parameter monomorphization: same higher-order function
called with different callables (named func, lambda, closure) must
dispatch each correctly via call_ptr, not hardcode the first one."""

def apply(func, x):
    return func(x)

def double(x):
    return x * 2

# Named function
print(apply(double, 5))            # 10

# Lambda — must NOT still call double
print(apply(lambda x: x + 1, 10))  # 11

# Closure
def make_adder(n):
    def adder(x):
        return x + n
    return adder

add5 = make_adder(5)
print(add5(3))                     # 8
print(apply(add5, 3))              # 8

# Compose two closures
def compose(f, g):
    def composed(x):
        return f(g(x))
    return composed

double_then_add5 = compose(add5, double)
print(double_then_add5(3))         # 11
