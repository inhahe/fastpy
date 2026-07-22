# Test: while True generator patterns
def counter(start=0):
    n = start
    while True:
        yield n
        n += 1

g = counter()
assert next(g) == 0
assert next(g) == 1
assert next(g) == 2

g2 = counter(10)
assert next(g2) == 10
assert next(g2) == 11

# Generator with break
def limited(n):
    i = 0
    while True:
        if i >= n:
            break
        yield i
        i += 1

assert list(limited(3)) == [0, 1, 2]
assert list(limited(0)) == []

print("ok")
