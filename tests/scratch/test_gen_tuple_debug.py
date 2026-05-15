# Debug: test each part separately
def pairs():
    yield (1, 2)
    yield (3, 4)

g = pairs()
t1 = next(g)
print(t1)
print(t1 == (1, 2))

t2 = next(g)
print(t2)
print(t2 == (3, 4))
