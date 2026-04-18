# Classes test program
# Tests class def, __init__, methods, inheritance, __str__, properties

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __str__(self):
        return f"Point({self.x}, {self.y})"

    def distance_to(self, other):
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5

p1 = Point(0, 0)
p2 = Point(3, 4)
print(p1)
print(p2)
print(f"distance: {p1.distance_to(p2)}")

# Inheritance
class Animal:
    def __init__(self, name):
        self.name = name

    def speak(self):
        return f"{self.name} says ..."

class Dog(Animal):
    def speak(self):
        return f"{self.name} says woof!"

class Cat(Animal):
    def speak(self):
        return f"{self.name} says meow!"

animals = [Dog("Rex"), Cat("Whiskers"), Dog("Buddy")]
for a in animals:
    print(a.speak())

# isinstance
print(isinstance(animals[0], Dog))
print(isinstance(animals[0], Animal))
print(isinstance(animals[0], Cat))

# Class with __repr__ and __eq__
class Fraction:
    def __init__(self, num, den):
        self.num = num
        self.den = den

    def __repr__(self):
        return f"Fraction({self.num}, {self.den})"

    def __eq__(self, other):
        if not isinstance(other, Fraction):
            return NotImplemented
        return self.num * other.den == other.num * self.den

    def __add__(self, other):
        return Fraction(
            self.num * other.den + other.num * self.den,
            self.den * other.den,
        )

f1 = Fraction(1, 2)
f2 = Fraction(1, 3)
f3 = f1 + f2
print(f"{f1} + {f2} = {f3}")
print(f"1/2 == 2/4? {Fraction(1, 2) == Fraction(2, 4)}")

# Static method and class method
class MathUtils:
    @staticmethod
    def gcd(a, b):
        while b:
            a, b = b, a % b
        return a

    @classmethod
    def from_string(cls, s):
        return cls()

print(f"gcd(12, 8) = {MathUtils.gcd(12, 8)}")
