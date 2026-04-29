# Regression: repr() dispatches to __repr__ on objects

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return "Point(" + str(self.x) + ", " + str(self.y) + ")"

    def __str__(self):
        return "(" + str(self.x) + ", " + str(self.y) + ")"

p = Point(3, 4)

# str() should use __str__
print(str(p))    # (3, 4)

# repr() should use __repr__
print(repr(p))   # Point(3, 4)

# print uses __str__
print(p)         # (3, 4)
