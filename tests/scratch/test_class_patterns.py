# Test class patterns

# 1. Inheritance with method override
class Animal:
    def __init__(self, name):
        self.name = name
    def speak(self):
        return self.name + " speaks"

class Dog(Animal):
    def speak(self):
        return self.name + " barks"

class Cat(Animal):
    def speak(self):
        return self.name + " meows"

d = Dog("Rex")
c = Cat("Whiskers")
print(d.speak())
print(c.speak())

# 2. Class with __str__
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def __str__(self):
        return "(" + str(self.x) + ", " + str(self.y) + ")"
    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y)

p1 = Point(1, 2)
p2 = Point(3, 4)
p3 = p1 + p2
print(p3)

# 3. Class with class variable
class Counter:
    count = 0
    def __init__(self):
        Counter.count = Counter.count + 1
    def get_count(self):
        return Counter.count

a = Counter()
b = Counter()
c = Counter()
print(c.get_count())

# 4. Property-like patterns
class Circle:
    def __init__(self, radius):
        self.radius = radius
    def area(self):
        return 3.14159 * self.radius * self.radius

c = Circle(5)
print(c.area())

# 5. Linked list
class Node:
    def __init__(self, val, next_node):
        self.val = val
        self.next_node = next_node

head = Node(1, Node(2, Node(3, None)))
current = head
vals = []
while current is not None:
    vals.append(current.val)
    current = current.next_node
print(vals)
