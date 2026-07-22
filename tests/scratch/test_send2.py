# Simpler: just the generator and next()/send()
def g():
    x = yield 10
    yield x * 2

c = g()
print(next(c))
print(c.send(5))
