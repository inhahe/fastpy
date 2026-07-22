# Test: try/except around next inside generator
def chars(s):
    it = iter(s)
    try:
        c = next(it)
    except StopIteration:
        c = ""
    yield c

g = chars("hi")
print(next(g))
