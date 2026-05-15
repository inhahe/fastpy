# Test: try/except around next in generator  
def chars(s):
    it = iter(s)
    done = False
    while not done:
        try:
            c = next(it)
        except StopIteration:
            done = True
        if not done:
            yield c

g = chars("hi")
print(next(g))
print(next(g))
