class Shape:
    def __init__(self, name):
        self.name = name
    def describe(self):
        return f"{self.name}: area={self.area()}"

class Circle(Shape):
    def __init__(self, r):
        self.name = "Circle"
        self.r = r
    def area(self):
        return 3 * self.r * self.r

c = Circle(5)
print(c.describe())
print(c.name)
print(c.area())
