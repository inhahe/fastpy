# Debug: print inside try block before yield
def chars(s):
    _iter_c = iter(s)
    try:
        c = next(_iter_c)
        print("GOT:", c)
    except StopIteration:
        c = ""
    yield c

g = chars("hi")
result = next(g)
print("RESULT:", result)
