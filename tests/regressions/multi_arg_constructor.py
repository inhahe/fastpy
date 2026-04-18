# Regression: constructors with 3 and 4 arguments
# Before fix: only obj_call_init0/1/2 existed in the runtime.
# Constructors with 3+ args raised CodeGenError.
# Fix: added obj_call_init3/4 (and obj_call_method3/4) to runtime and codegen.

# 3-arg constructor with mixed types
class Color:
    def __init__(self, r, g, b):
        self.r = r
        self.g = g
        self.b = b

    def __str__(self):
        return "rgb(" + str(self.r) + "," + str(self.g) + "," + str(self.b) + ")"

c = Color(255, 128, 0)
print(c)
print(c.r)
print(c.g)
print(c.b)

# 3-arg constructor with string + int + float
class Item:
    def __init__(self, name, qty, price):
        self.name = name
        self.qty = qty
        self.price = price

    def total(self):
        return self.qty * self.price

item = Item("Widget", 5, 3.99)
print(item.name)
print(item.qty)
print(item.total())

# 3-arg constructor with float physics
class Particle:
    def __init__(self, pos, vel, acc):
        self.pos = pos
        self.vel = vel
        self.acc = acc

    def step(self, dt):
        self.vel = self.vel + self.acc * dt
        self.pos = self.pos + self.vel * dt

    def get_pos(self):
        return self.pos

p = Particle(0.0, 0.0, 9.8)
p.step(1.0)
print(p.get_pos())

# 4-arg constructor
class Rect:
    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def area(self):
        return self.w * self.h

r = Rect(10, 20, 100, 50)
print(r.area())

# 3-arg inheritance
class Base:
    def __init__(self, x):
        self.x = x

class Child(Base):
    def __init__(self, x, y, z):
        Base.__init__(self, x)
        self.y = y
        self.z = z

    def total(self):
        return self.x + self.y + self.z

leaf = Child(1, 2, 3)
print(leaf.total())
