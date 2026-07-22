# Test: generator yielding tuples
def pairs():
    yield (1, 2)
    yield (3, 4)

g = pairs()
print(next(g))
print(next(g))
