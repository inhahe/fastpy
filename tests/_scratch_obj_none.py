# Test: method returning self.attr where attr can be str or None
class Foo:
    def __init__(self, x=None):
        self.x = x
    def get(self):
        return self.x

# Test 1: Only None (no string call first)
b = Foo()
print(b.get())

# Test 2: String first, then None
a = Foo('hello')
print(a.get())
c = Foo()
print(c.get())
