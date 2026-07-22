def g():
    x = yield 0
    print("x is", x)
    r = x * 2
    print("r is", r)
    yield r

c = g()
v1 = next(c)
print("v1:", v1)
v2 = c.send(5)
print("v2:", v2)
