# Minimal: generator yields literal strings
def gen():
    yield "a"
    yield "b"
g = gen()
print(next(g))
print(next(g))
