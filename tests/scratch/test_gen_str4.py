# Test: store iter result in generator attribute, then call next
def chars(s):
    it = iter(s)
    c = next(it)
    yield c

g = chars("hi")
print(next(g))
