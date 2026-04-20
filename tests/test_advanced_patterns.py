"""Test more advanced Python patterns."""

# 1. Nested functions / closures
def make_adder(n):
    def adder(x):
        return x + n
    return adder

add5 = make_adder(5)
print(add5(10))  # 15

# 2. Class with __repr__ and __eq__
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def distance_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx*dx + dy*dy) ** 0.5

p1 = Point(0, 0)
p2 = Point(3, 4)
print(p1.distance_to(p2))  # 5.0

# 3. Inheritance with method override
class Animal:
    def __init__(self, name):
        self.name = name
    def speak(self):
        return "..."

class Dog(Animal):
    def speak(self):
        return self.name + " says woof"

class Cat(Animal):
    def speak(self):
        return self.name + " says meow"

animals = [Dog("Rex"), Cat("Whiskers"), Dog("Buddy")]
for a in animals:
    print(a.speak())

# 4. Generator
def fib_gen(n):
    a, b = 0, 1
    i = 0
    while i < n:
        yield a
        a, b = b, a + b
        i += 1

fibs = list(fib_gen(8))
print(fibs[7])  # 13

# 5. with statement (file-like)
class Ctx:
    def __enter__(self):
        print("enter")
        return self
    def __exit__(self, *args):
        print("exit")

with Ctx() as c:
    print("inside")

print("advanced patterns passed!")
