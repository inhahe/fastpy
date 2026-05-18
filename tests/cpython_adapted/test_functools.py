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

# reduce for string building
words = ["hello", "world", "from", "python"]
print(reduce(lambda a, b: a + " " + b, words))

# reduce for max
nums = [3, 1, 4, 1, 5, 9, 2, 6]
print(reduce(lambda a, b: a if a > b else b, nums))

# partial-like pattern (closure)
def partial(func, *fixed_args):
    def wrapper(*args):
        all_args = list(fixed_args) + list(args)
        return func(*all_args)
    return wrapper

def power(base, exp):
    return base ** exp

square = partial(power, 2)
# Note: can't use *args, so manual version:

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

# Memoize pattern
def memoize(func):
    cache = {}
    def wrapper(n):
        if n in cache:
            return cache[n]
        result = func(n)
        cache[n] = result
        return result
    return wrapper

call_count = [0]

def fib_raw(n):
    call_count[0] += 1
    if n <= 1:
        return n
    return fib_memo(n - 1) + fib_memo(n - 2)

fib_memo = memoize(fib_raw)

print(fib_memo(10))
print(fib_memo(20))
print(fib_memo(30))
print("calls:", call_count[0])

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

# LRU cache simulation (bounded dict)
def lru_cache(maxsize):
    def decorator(func):
        cache = {}
        order = []
        def wrapper(n):
            if n in cache:
                return cache[n]
            result = func(n)
            cache[n] = result
            order.append(n)
            if len(order) > maxsize:
                oldest = order.pop(0)
                del cache[oldest]
            return result
        wrapper.cache_size = lambda: len(cache)
        return wrapper
    return decorator

@lru_cache(5)
def expensive(n):
    return n * n * n

for i in range(10):
    print(expensive(i), end=" ")
print()
print(expensive.cache_size())
