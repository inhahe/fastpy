# Test: multiple yields inside try/except
def gen():
    try:
        yield 1
        yield 2
        yield 3
    except Exception:
        yield -1

g = gen()
print(next(g))
print(next(g))
print(next(g))
