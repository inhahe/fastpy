# Minimal: generator yield tuple
def gen():
    yield (1, 2)

g = gen()
t = next(g)
print(t)
print(type(t))
