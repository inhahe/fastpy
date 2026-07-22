# Regression: Parent.__init__(self, x) call in child class __init__
#
# Bug: _csa_scan_and_merge registered A.__init__(self, x) under the bare
# "__init__" key in _call_site_param_types, with arg types including `self`
# (e.g., ['obj', None]).  This polluted ALL __init__ methods: when Temp's
# __init__ body was emitted, it looked up the bare "__init__" key and
# misinterpreted the 'obj' (self arg from A.__init__) as the type of Temp's
# first user parameter (celsius).  Result: celsius was treated as an OBJ
# pointer; when its default was 0.0 (i64 bits = 0), the null-check tagged it
# as None instead of float.
#
# Fix: Skip registration of Parent.__init__(self, x) calls in CSA entirely —
# the parent's param types are already propagated through the constructor
# inheritance chain (Car(60.0) → Vehicle types via class_parents).
# Also: __init__ methods never fall back to bare "__init__" key — they use
# qualified "Class.__init__" or class-name constructor types only.

# Case 1: basic parent init call
class A:
    def __init__(self, x):
        self.x = x

class B(A):
    def __init__(self, x, y):
        A.__init__(self, x)
        self.y = y

b = B(10, 20)
print(b.x)
print(b.y)

# Case 2: parent init with float propagation
class Vehicle:
    def __init__(self, speed):
        self.speed = speed

    def travel_time(self, distance):
        return distance / self.speed

class Car(Vehicle):
    def __init__(self, speed, fuel):
        Vehicle.__init__(self, speed)
        self.fuel = fuel

car = Car(60.0, 50.0)
print(car.speed)
print(car.fuel)
print(car.travel_time(120.0))

# Case 3: default param not polluted by parent init in another class
class Temp:
    def __init__(self, celsius=0.0):
        self.celsius = celsius

t1 = Temp()
print(t1.celsius)
t2 = Temp(100.0)
print(t2.celsius)

# Case 4: int default not polluted
class Config:
    def __init__(self, val=42):
        self.val = val

c = Config()
print(c.val)

# Case 5: multi-level inheritance
class Base:
    def __init__(self, x):
        self.x = x

class Mid(Base):
    def __init__(self, x, y):
        Base.__init__(self, x)
        self.y = y

class Top(Mid):
    def __init__(self, x, y, z):
        Mid.__init__(self, x, y)
        self.z = z

t = Top(1, 2, 3)
print(t.x, t.y, t.z)

# Case 6: parent init with different param types than child constructor
# Circle(5) passes int, but Shape.__init__ receives "circle" (str) through
# the explicit parent init call.
class Shape:
    def __init__(self, name):
        self.name = name

    def describe(self):
        return self.name

class Circle(Shape):
    def __init__(self, r):
        Shape.__init__(self, "circle")
        self.r = r

c = Circle(5)
print(c.describe())
print(c.r)
