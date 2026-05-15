# Test: generator yielding mixed types
def mixed():
    yield 1
    yield "hello"
    yield 3.14
    yield None
    yield True

g = mixed()
for _ in range(5):
    print(next(g))
