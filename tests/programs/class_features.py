# Class features: super(), property, __eq__, __str__, multi-level inheritance

class Base:
    def __init__(self, x):
        self.x = x
    def describe(self):
        return f"Base(x={self.x})"

class Middle(Base):
    def __init__(self, x, y):
        super().__init__(x)
        self.y = y
    def describe(self):
        return f"Middle(x={self.x}, y={self.y})"

class Leaf(Middle):
    def __init__(self, x, y, z):
        super().__init__(x, y)
        self.z = z
    def describe(self):
        return f"Leaf({self.x}, {self.y}, {self.z})"

obj = Leaf(1, 2, 3)
print(obj.describe())
print(isinstance(obj, Base))

class Temperature:
    def __init__(self, celsius):
        self._celsius = celsius
    @property
    def fahrenheit(self):
        return self._celsius * 9 / 5 + 32
    @property
    def celsius(self):
        return self._celsius
    @celsius.setter
    def celsius(self, val):
        self._celsius = val
    def __eq__(self, other):
        return isinstance(other, Temperature) and self._celsius == other._celsius
    def __str__(self):
        return f"{self._celsius}C"

t = Temperature(100)
print(t.fahrenheit)
print(t)
t.celsius = 0
print(t.fahrenheit)
print(Temperature(100) == Temperature(100))
print(Temperature(100) == Temperature(50))

print("tests passed!")
