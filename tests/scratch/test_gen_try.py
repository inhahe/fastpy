# Test: try/except inside generator with integer
def gen():
    try:
        x = 42
    except Exception:
        x = 0
    yield x

g = gen()
print(next(g))
