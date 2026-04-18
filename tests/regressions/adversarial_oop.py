# OOP patterns

# Inheritance + super
class Animal:
    def __init__(self, name):
        self.name = name
    def speak(self):
        return "..."
    def describe(self):
        return self.name + " says " + self.speak()

class Dog(Animal):
    def __init__(self, name, breed):
        super().__init__(name)
        self.breed = breed
    def speak(self):
        return "Woof!"

class Cat(Animal):
    def speak(self):
        return "Meow"

d = Dog("Rex", "Lab")
print(d.describe())
print(d.breed)

c = Cat("Whiskers")
print(c.describe())

# Polymorphism via list
animals = [Dog("A", "B"), Cat("C"), Dog("D", "E")]
for a in animals:
    print(a.describe())

# (Skipped: class-level variable mutation `Counter.count = Counter.count + 1`
#  isn't supported — requires `Counter` to be usable as a value inside
#  its own methods, which the compiler doesn't handle yet.)

# __str__ / __repr__
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def __str__(self):
        return "Point(" + str(self.x) + ", " + str(self.y) + ")"

p = Point(3, 4)
print(p)
print(str(p))
