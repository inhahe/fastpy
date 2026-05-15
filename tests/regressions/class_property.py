# Regression: @property decorator with getter and setter

class Circle:
    def __init__(self, radius):
        self._radius = radius

    @property
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        if value < 0:
            self._radius = 0
        else:
            self._radius = value

    @property
    def area(self):
        return 3 * self._radius * self._radius


c = Circle(5)
print(c.radius)         # 5
print(c.area)           # 75

c.radius = 10
print(c.radius)         # 10
print(c.area)           # 300

# Negative value clamps to 0
c.radius = -3
print(c.radius)         # 0


# Read-only property (no setter)
class Square:
    def __init__(self, side):
        self._side = side

    @property
    def perimeter(self):
        return 4 * self._side


sq = Square(6)
print(sq.perimeter)     # 24
