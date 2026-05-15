# Bug 14: Abstract class instantiation doesn't raise TypeError
from abc import ABC, abstractmethod

class Shape(ABC):
    @abstractmethod
    def area(self):
        pass

try:
    s = Shape()
    print("no error")
except TypeError as e:
    print("caught TypeError")

# Concrete subclass should work fine
class Circle(Shape):
    def __init__(self, r):
        self.r = r
    def area(self):
        return 3.14 * self.r * self.r

c = Circle(5)
print(c.area())

# Partial implementation should also fail
class Partial(Shape):
    pass

try:
    p = Partial()
    print("no error")
except TypeError:
    print("caught partial TypeError")

# Multiple abstract methods
class Animal(ABC):
    @abstractmethod
    def speak(self):
        pass
    @abstractmethod
    def move(self):
        pass

class Dog(Animal):
    def speak(self):
        return "Woof"
    def move(self):
        return "Run"

d = Dog()
print(d.speak())
print(d.move())
