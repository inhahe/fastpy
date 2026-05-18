# Adapted from CPython Lib/test/test_class.py
# Tests class definition and basic OOP

# Basic class
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def distance_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5

    def translate(self, dx, dy):
        return Point(self.x + dx, self.y + dy)

p1 = Point(0, 0)
p2 = Point(3, 4)
print(p1.x, p1.y)
print(p2.x, p2.y)
print(p1.distance_to(p2))

p3 = p1.translate(1, 2)
print(p3.x, p3.y)

# Inheritance
class Shape:
    def __init__(self, name):
        self.name = name

    def area(self):
        return 0

    def describe(self):
        return self.name + ": area=" + str(self.area())

class Rectangle(Shape):
    def __init__(self, width, height):
        Shape.__init__(self, "Rectangle")
        self.width = width
        self.height = height

    def area(self):
        return self.width * self.height

class Circle(Shape):
    def __init__(self, radius):
        Shape.__init__(self, "Circle")
        self.radius = radius

    def area(self):
        return 3.14159 * self.radius * self.radius

r = Rectangle(5, 3)
c = Circle(4)
print(r.describe())
print(c.describe())

# Method calls on list of objects
shapes = [Rectangle(2, 3), Circle(1), Rectangle(4, 5), Circle(2)]
for s in shapes:
    print(s.name, round(s.area(), 2))

# Self-reference
class Node:
    def __init__(self, value, next_node=None):
        self.value = value
        self.next = next_node

    def to_list(self):
        result = []
        current = self
        while current is not None:
            result.append(current.value)
            current = current.next
        return result

n3 = Node(3)
n2 = Node(2, n3)
n1 = Node(1, n2)
print(n1.to_list())

# Class with multiple methods
class Stack:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def pop(self):
        return self.items.pop()

    def peek(self):
        return self.items[-1]

    def is_empty(self):
        return len(self.items) == 0

    def size(self):
        return len(self.items)

st = Stack()
print(st.is_empty())
st.push(1)
st.push(2)
st.push(3)
print(st.size())
print(st.peek())
print(st.pop())
print(st.pop())
print(st.size())
print(st.is_empty())

# Class variables vs instance variables
class Counter:
    count = 0

    def __init__(self, name):
        self.name = name
        Counter.count += 1

    def get_total(self):
        return Counter.count

c1 = Counter("a")
c2 = Counter("b")
c3 = Counter("c")
print(c3.get_total())
print(c1.name, c2.name, c3.name)

# isinstance
print(isinstance(r, Rectangle))
print(isinstance(r, Shape))
print(isinstance(c, Rectangle))
print(isinstance(c, Shape))
print(isinstance(42, int))
print(isinstance("hello", str))
