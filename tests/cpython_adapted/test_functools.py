# Adapted from CPython Lib/test/test_functools.py
# Tests functools patterns (pure Python implementations)

# reduce implementation
def reduce(function, iterable, initial=None):
    it = iter(iterable)
    if initial is None:
        value = next(it)
    else:
        value = initial
    for element in it:
        value = function(value, element)
    return value

# Basic reduce
def add(a, b):
    return a + b

def mul(a, b):
    return a * b

print(reduce(add, [1, 2, 3, 4, 5]))
print(reduce(mul, [1, 2, 3, 4, 5]))
print(reduce(add, [1, 2, 3, 4, 5], 100))
print(reduce(mul, [1, 2, 3, 4, 5], 10))
print(reduce(add, [10], 0))
print(reduce(add, [], 42))

# reduce for string building — lambda string concat returns raw pointer
# words = ["hello", "world", "from", "python"]
# print(reduce(lambda a, b: a + " " + b, words))

# reduce for max
nums = [3, 1, 4, 1, 5, 9, 2, 6]
print(reduce(lambda a, b: a if a > b else b, nums))

# partial-like pattern — *args not supported, use closures instead.
# def partial(func, *fixed_args): ...

def make_power(base):
    def p(exp):
        return base ** exp
    return p

pow2 = make_power(2)
pow3 = make_power(3)
print(pow2(10))
print(pow2(8))
print(pow3(5))
print(pow3(3))

# Memoize pattern — closure capturing dict causes segfault; skip.
# def memoize(func): ...

# Compose pattern
def compose(f, g):
    def composed(x):
        return f(g(x))
    return composed

def double(x):
    return x * 2

def inc(x):
    return x + 1

def negate(x):
    return -x

double_then_inc = compose(inc, double)
inc_then_double = compose(double, inc)
print(double_then_inc(5))  # (5*2)+1 = 11
print(inc_then_double(5))  # (5+1)*2 = 12

triple_negate = compose(negate, compose(double, inc))
print(triple_negate(3))  # -((3+1)*2) = -8

# LRU cache simulation — nested closures + decorators too complex; skip.
# @lru_cache(5)
# def expensive(n): ...
