# Regression: @property setter and property in f-strings with format spec

class Circle:
    def __init__(self, radius):
        self._radius = radius
    @property
    def area(self):
        return 3.14159 * self._radius ** 2
    @property
    def radius(self):
        return self._radius
    @radius.setter
    def radius(self, value):
        self._radius = value

c = Circle(5)
# Property getter
print(c.radius)
print(c.area)

# Property setter
c.radius = 10
print(c.radius)
print(c.area)

# Property in f-string
print(f"r={c.radius}")
print(f"area={c.area:.2f}")

# Property getter without setter
class Box:
    def __init__(self, val):
        self._val = val
    @property
    def val(self):
        return self._val
    @val.setter
    def val(self, v):
        self._val = v

b = Box(42)
print(b.val)
b.val = 99
print(b.val)
