class Inner:
    def __init__(self, v):
        self.value = v

class Outer:
    def __init__(self):
        self.inner = Inner(42)
        self.tag = "outer"

o = Outer()
print(o.inner.value)
print(o.tag)

class A:
    def __init__(self):
        self.n = 10

class B:
    def __init__(self):
        self.a = A()

b = B()
print(b.a.n)
