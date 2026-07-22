# Test: try/except inside generator with string assignment
def gen(s):
    try:
        c = s
    except Exception:
        c = ""
    yield c

g = gen("hello")
print(next(g))
