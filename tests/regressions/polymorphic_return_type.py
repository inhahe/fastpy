"""Regression test: polymorphic method return types.

When a base class method returns int and a subclass method returns float,
the virtual dispatch must handle the calling convention difference
(integer returns in RAX, float returns in XMM0 on x86-64).

Previously this caused an LLVM IR type mismatch error or returned
garbage values because the dispatch assumed all overrides share
the base class return type.
"""


class Shape:
    def area(self):
        return 0

class Circle(Shape):
    def __init__(self, r):
        self.r = r
    def area(self):
        return 3.14159 * self.r * self.r

class Square(Shape):
    def __init__(self, s):
        self.s = s
    def area(self):
        return self.s * self.s

# Test 1: direct calls (should work)
c = Circle(5)
print(c.area())
sq = Square(4)
print(sq.area())

# Test 2: polymorphic dispatch through a list
shapes = [Circle(5), Square(4)]
for s in shapes:
    print(s.area())

# Test 3: base class instance
sh = Shape()
print(sh.area())
