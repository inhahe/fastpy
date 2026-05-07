# Regression: generator state-machine expansion and lazy iteration.
# Before fix: simple generators used eager list-collection which broke:
# - Infinite generators (while True: yield ...) hung during collection
# - next() on generators crashed (list has no __next__)
# - enumerate(generator) on infinite generators hung

# 1. Simple sequential generator with next()
def gen3():
    yield 10
    yield 20
    yield 30

g = gen3()
print(next(g))
print(next(g))
print(next(g))

# 2. Infinite generator with for-loop break
def counter():
    n = 0
    while True:
        yield n
        n = n + 1

vals = []
for x in counter():
    vals.append(x)
    if x >= 4:
        break
print(vals)

# 3. Bounded while-loop generator (fibonacci)
def fib():
    a, b = 0, 1
    while a < 50:
        yield a
        a, b = b, a + b

print(list(fib()))

# 4. Generator with parameter
def count_from(start):
    n = start
    while n < start + 3:
        yield n
        n = n + 1

print(list(count_from(10)))

# 5. enumerate() on finite generator
result = []
for i, x in enumerate(gen3()):
    result.append((i, x))
print(result)

# 6. enumerate() on infinite generator with break
result2 = []
for i, x in enumerate(counter()):
    result2.append(x)
    if i >= 2:
        break
print(result2)

# 7. next() on while-loop generator
g2 = counter()
print(next(g2))
print(next(g2))
print(next(g2))

# 8. Generator with multiple yields and state
def alternating():
    yield "a"
    yield "b"
    yield "c"

print(list(alternating()))
