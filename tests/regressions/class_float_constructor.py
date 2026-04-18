# Regression: class constructors with float arguments crashed or gave wrong output
#
# Bug 1 (crash): _emit_constructor only converted pointer args to i64 (ptrtoint)
# but not double args. obj_call_init1(i8*, i64) got a double → LLVM type error.
# Fix: added double→i64 bitcast and narrow int→i64 zext in _emit_constructor
# (both actual args and defaults paths) and obj_call_method dispatch.
#
# Bug 2 (wrong output): inside __init__, the float param arrived as i64 but
# _emit_method_body didn't recognize it as float. Stored attrs with FPY_TAG_INT
# instead of FPY_TAG_FLOAT, so print showed raw i64 bits.
# Fix: (a) _emit_method_body now checks call_tag=="float" and float defaults,
# bitcasting i64→double. (b) _analyze_call_sites extends existing when a later
# call provides more args. (c) _detect_class_float_attrs detects float attrs
# from call-site params and float defaults. (d) _emit_attr_load uses
# _class_float_attrs to bitcast i64→double on load. (e) _declare_class return
# type detection checks self.float_attr and float params.

class Circle:
    def __init__(self, r):
        self.radius = r

    def diameter(self):
        return self.radius * 2.0

    def is_big(self):
        return self.radius > 10.0

c1 = Circle(5.0)
print(c1.radius)
print(c1.diameter())
print(c1.is_big())

c2 = Circle(15.0)
print(c2.diameter())
print(c2.is_big())

# Two float attributes
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def distance(self):
        return (self.x * self.x + self.y * self.y) ** 0.5

p = Point(3.0, 4.0)
print(p.x)
print(p.y)
print(p.distance())

# Float default value
class Temp:
    def __init__(self, celsius=0.0):
        self.celsius = celsius

    def to_fahrenheit(self):
        return self.celsius * 1.8 + 32.0

t1 = Temp()
print(t1.celsius)
print(t1.to_fahrenheit())
t2 = Temp(100.0)
print(t2.celsius)
print(t2.to_fahrenheit())

# Float attr initialized with literal in __init__
class Accumulator:
    def __init__(self):
        self.total = 0.0

    def add(self, val):
        self.total = self.total + val

    def get(self):
        return self.total

a = Accumulator()
a.add(1.5)
a.add(2.5)
print(a.get())

# Method with float argument
class Box:
    def __init__(self, w, h):
        self.width = w
        self.height = h

    def scale(self, factor):
        return self.width * factor

b = Box(10.0, 20.0)
print(b.width)
print(b.height)
print(b.scale(2.5))

# Inherited float attrs from parent class
class Shape:
    def __init__(self, size):
        self.size = size

    def area(self):
        return self.size * self.size

class Square(Shape):
    def perimeter(self):
        return self.size * 4.0

sq = Square(5.0)
print(sq.area())
print(sq.perimeter())

# Method returning int() of float attr
class Score:
    def __init__(self, value):
        self.value = value

    def rounded(self):
        return int(self.value)

sc = Score(3.7)
print(sc.value)
print(sc.rounded())

# Negative float literal argument (-2.0 is UnaryOp, not Constant)
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

v = Vector(3.5, -2.0)
print(v.x)
print(v.y)

# Bool method return assigned to variable (dispatch returns i64, must trunc to i32)
class Checker:
    def __init__(self, limit):
        self.limit = limit

    def above(self, x):
        return x > self.limit

ch = Checker(50)
res = ch.above(75)
print(res)
res2 = ch.above(25)
print(res2)

# Float loop variable tracking (for r in [1.0, 2.0])
for radius in [1.0, 2.0, 3.0]:
    circ = Circle(radius)
    print(circ.diameter())

# Bool attr returned from method (return self.bool_attr needs i32 ret type)
class Toggle:
    def __init__(self):
        self.state = False

    def flip(self):
        self.state = not self.state

    def is_on(self):
        return self.state

tog = Toggle()
print(tog.is_on())
tog.flip()
print(tog.is_on())

# Bool param passed to constructor
class Gate:
    def __init__(self, open):
        self.open = open

    def is_open(self):
        return self.open

gate = Gate(True)
print(gate.is_open())

# Parent init with float propagation
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
