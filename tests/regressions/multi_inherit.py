# Regression: multiple inheritance slot layout
# Previously, secondary base methods used their own class's slot
# indices which differed from the child class's renumbered layout,
# causing attributes to be stored/read at wrong slots.

# Case 1: Two parents with their own attrs
class Animal:
    def __init__(self, name):
        self.name = name

    def speak(self):
        return f"{self.name} makes a sound"

class Pet:
    def __init__(self, owner):
        self.owner = owner

    def who_owns(self):
        return f"Owned by {self.owner}"

class Dog(Animal, Pet):
    def __init__(self, name, owner):
        Animal.__init__(self, name)
        Pet.__init__(self, owner)

    def speak(self):
        return f"{self.name} says Woof!"

d = Dog("Rex", "Alice")
print(d.speak())
print(d.name)
print(d.who_owns())
print(d.owner)

# Case 2: Mixin pattern (base reads attrs it doesn't define)
class JsonMixin:
    def to_json(self):
        return f'{{"name": "{self.name}", "value": {self.value}}}'

class Config(JsonMixin):
    def __init__(self, name, value):
        self.name = name
        self.value = value

c = Config("timeout", 30)
print(c.to_json())

# Case 3: Diamond inheritance
class Base:
    def __init__(self, x):
        self.x = x
    def show(self):
        return f"x={self.x}"

class Left(Base):
    def __init__(self, x, y):
        Base.__init__(self, x)
        self.y = y

class Right(Base):
    def __init__(self, x, z):
        Base.__init__(self, x)
        self.z = z

class Diamond(Left, Right):
    def __init__(self, x, y, z):
        Left.__init__(self, x, y)
        Right.__init__(self, x, z)

dm = Diamond(1, 2, 3)
print(dm.x)
print(dm.y)
print(dm.z)
print(dm.show())

# Case 4: Three-way multiple inheritance
class P:
    def __init__(self):
        self.p = 10
    def get_p(self):
        return self.p

class Q:
    def __init__(self):
        self.q = 20
    def get_q(self):
        return self.q

class R:
    def __init__(self):
        self.r = 30
    def get_r(self):
        return self.r

class PQR(P, Q, R):
    def __init__(self):
        P.__init__(self)
        Q.__init__(self)
        R.__init__(self)

pqr = PQR()
print(pqr.get_p())
print(pqr.get_q())
print(pqr.get_r())
