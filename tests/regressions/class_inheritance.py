# Regression: basic class inheritance with method override and super().__init__

class Animal:
    def __init__(self, name):
        self.name = name

    def speak(self):
        return "..."

    def get_name(self):
        return self.name


class Dog(Animal):
    def __init__(self, name, breed):
        super().__init__(name)
        self.breed = breed

    def speak(self):
        return "Woof"


class Cat(Animal):
    def __init__(self, name):
        super().__init__(name)

    def speak(self):
        return "Meow"


d = Dog("Rex", "Lab")
print(d.get_name())     # Rex
print(d.speak())        # Woof
print(d.breed)          # Lab

c = Cat("Whiskers")
print(c.get_name())     # Whiskers
print(c.speak())        # Meow

a = Animal("Thing")
print(a.speak())        # ...
