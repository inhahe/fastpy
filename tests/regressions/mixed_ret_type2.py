# Regression: mixed return types - more complex scenarios
# Verifies: polymorphic dispatch with mixed int/float/string returns

class Animal:
    def __init__(self, name):
        self.name = name

    def sound(self):
        return "..."

    def speed(self):
        return 0.0

class Dog(Animal):
    def sound(self):
        return "woof"

    def speed(self):
        return 35  # int, not float

class Cat(Animal):
    def sound(self):
        return "meow"

    def speed(self):
        return 30.5  # float

# Direct calls
d = Dog("Rex")
print(d.sound())  # woof
print(d.speed())  # 35

c = Cat("Whiskers")
print(c.sound())  # meow
print(c.speed())  # 30.5

# Polymorphic
animals = [Dog("Rex"), Cat("Whiskers"), Animal("?")]
for a in animals:
    print(a.sound(), a.speed())
# woof 35
# meow 30.5
# ... 0.0
