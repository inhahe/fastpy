# Test: send(None) should behave like next()
def gen():
    x = yield 0
    print(x)
    yield 1

g = gen()
print(next(g))     # 0
print(g.send(None)) # Should print: None then 1
