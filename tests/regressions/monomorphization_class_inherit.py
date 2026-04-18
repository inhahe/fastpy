# Regression: inheritance with monomorphized classes.

class Base:
    def __init__(self, x):
        self.x = x
    def get_x(self):
        return self.x


class Child(Base):
    def __init__(self, x, y):
        super().__init__(x)
        self.y = y


# Base used with both int and float — triggers class monomorphization
b1 = Base(5)
b2 = Base(2.5)
print(b1.get_x())     # expected: 5
print(b2.get_x())     # expected: 2.5

# Child — for now, only uses int
c1 = Child(7, 8)
print(c1.get_x())     # expected: 7
print(c1.y)           # expected: 8
