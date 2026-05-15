def g():
    x=yield
    yield x*2
c=g();next(c);print(c.send(5))
