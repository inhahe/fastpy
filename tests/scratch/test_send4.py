# Try with print to see if expansion works
def g():
    x = yield 0
    print("got", x)
    yield x * 2

c = g()
v1 = next(c)
print("v1:", v1)
v2 = c.send(5)
print("v2:", v2)
