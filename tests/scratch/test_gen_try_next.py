# Test: try/except around next() inside generator  
def gen(s):
    it = iter(s)
    try:
        c = next(it)
    except StopIteration:
        c = ""
    yield c

g = gen("hi")
print(next(g))
