# Regression tests for Bugs 3, 4, 5, 6, 7, 8, 9, 11

# Bug 6: hasattr() returns False for missing attributes
class Obj:
    def __init__(self):
        self.x = 1
o = Obj()
print(hasattr(o, "x"))
print(hasattr(o, "y"))
o.w = 42
print(hasattr(o, "w"))

# Bug 7: getattr() with default returns default for missing attrs
class Obj2:
    def __init__(self):
        self.a = 10
o2 = Obj2()
print(getattr(o2, "a", "default"))
print(getattr(o2, "b", "default"))
print(getattr(o2, "c", 99))

# Bug 9: next() with default returns default when exhausted
it = iter([1, 2])
print(next(it))
print(next(it))
print(next(it, "done"))

def gen():
    yield 10
    yield 20
g = gen()
print(next(g))
print(next(g))
print(next(g, "finished"))

# Bug 4: match statement second list-pattern case
x = ["b", "hello"]
match x:
    case ["a", y]:
        print(y)
    case ["b", y]:
        print(y + "!")

# Bug 5: with statement with multiple context managers
class Ctx:
    def __init__(self, n):
        self.n = n
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

with Ctx(1) as a, Ctx(2) as b:
    print(a.n, b.n)

# Bug 8: issubclass() for user-defined classes
class A:
    pass
class B(A):
    pass
class C(B):
    pass
print(issubclass(B, A))
print(issubclass(C, A))
print(issubclass(A, B))

# Bug 11: property deleter
class PropClass:
    def __init__(self):
        self._val = 10
    @property
    def val(self):
        return self._val
    @val.setter
    def val(self, v):
        self._val = v
    @val.deleter
    def val(self):
        self._val = 0

pc = PropClass()
print(pc.val)
pc.val = 42
print(pc.val)
del pc.val
print(pc.val)

# Bug 3: except* multiple clauses
try:
    raise ExceptionGroup("e", [ValueError("a"), TypeError("b")])
except* ValueError:
    print("caught ValueError")
except* TypeError:
    print("caught TypeError")
