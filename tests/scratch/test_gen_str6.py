# Test: simpler - just yield result of next(iter(s))
def chars(s):
    it = iter(s)
    c = next(it)
    yield c
    c = next(it)
    yield c

g = chars("hi")
print(next(g))
print(next(g))
