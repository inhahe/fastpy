# Test: try/except around next, store to attribute
class Foo:
    def __init__(self, s):
        self.s = s
        self.c = ""
    def go(self):
        it = iter(self.s)
        try:
            self.c = next(it)
        except StopIteration:
            self.c = ""
        return self.c

f = Foo("hi")
print(f.go())
