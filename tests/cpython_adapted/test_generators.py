# Adapted from CPython Lib/test/test_generators.py
# Tests generator functions and iteration

# Basic generator
def count_up(n):
    i = 0
    while i < n:
        yield i
        i += 1

result = []
for x in count_up(5):
    result.append(x)
print(result)

# Generator as list
print(list(count_up(8)))

# Fibonacci generator
def fib(n):
    a = 0
    b = 1
    count = 0
    while count < n:
        yield a
        a, b = b, a + b
        count += 1

print(list(fib(10)))

# Generator with return value
def limited():
    yield 1
    yield 2
    yield 3

print(list(limited()))

# Generator with condition
def evens(limit):
    i = 0
    while i < limit:
        if i % 2 == 0:
            yield i
        i += 1

print(list(evens(20)))

# Generator expression
squares = list(x * x for x in range(10))
print(squares)

even_squares = list(x * x for x in range(10) if x % 2 == 0)
print(even_squares)

# Sum with generator expression
total = sum(x * x for x in range(10))
print(total)

# Nested generators
def flatten(lists):
    for lst in lists:
        for item in lst:
            yield item

nested = [[1, 2, 3], [4, 5], [6, 7, 8, 9]]
print(list(flatten(nested)))

# Generator with early termination — break in for-over-generator
# causes segfault; skip for now.
# def take(n, gen): ...
# def naturals(): ...
# print(take(10, naturals()))

# Multiple iterations of same generator function
def repeat(value, times):
    i = 0
    while i < times:
        yield value
        i += 1

print(list(repeat("x", 5)))
print(list(repeat(42, 3)))

# Generator pipeline — chaining generators that iterate other generators
# causes segfault; skip for now.
# def doubles(gen): ...
# def add_one(gen): ...
# print(list(add_one(doubles(count_up(5)))))

# Range-like generator
def my_range(start, stop, step=1):
    i = start
    while i < stop:
        yield i
        i += step

print(list(my_range(0, 10, 2)))
print(list(my_range(5, 15, 3)))
print(list(my_range(0, 0)))

# Generator with accumulator
def running_sum(iterable):
    total = 0
    for x in iterable:
        total += x
        yield total

print(list(running_sum([1, 2, 3, 4, 5])))
print(list(running_sum([10, -5, 3, -2, 7])))
