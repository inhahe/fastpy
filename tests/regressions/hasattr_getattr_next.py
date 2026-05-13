# hasattr() must return False for missing attributes (Bug 6)
class Obj:
    def __init__(self):
        self.x = 1

o = Obj()
print(hasattr(o, "x"))
print(hasattr(o, "y"))
print(hasattr(o, "z"))

# Dynamic attr
o.w = 42
print(hasattr(o, "w"))

# getattr() with default must return default for missing attrs (Bug 7)
class Obj2:
    def __init__(self):
        self.a = 10

o2 = Obj2()
print(getattr(o2, "a", "default"))
print(getattr(o2, "b", "default"))
print(getattr(o2, "c", 99))

# 2-arg getattr still works
print(getattr(o2, "a"))

# next() with default must return default when exhausted (Bug 9)
it = iter([1, 2])
print(next(it))
print(next(it))
print(next(it, "done"))
print(next(it, 42))

# Works with generators too
def gen():
    yield 10
    yield 20

g = gen()
print(next(g))
print(next(g))
print(next(g, "finished"))
