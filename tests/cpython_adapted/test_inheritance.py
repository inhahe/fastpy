# Adapted from CPython Lib/test/test_class.py (inheritance portions)
# Tests class inheritance and method resolution

# Single inheritance chain
class A:
    def method(self):
        return "A"
    def base_method(self):
        return "base"

class B(A):
    def method(self):
        return "B"

class C(B):
    def method(self):
        return "C"

a = A()
b = B()
c = C()
print(a.method())
print(b.method())
print(c.method())
print(c.base_method())  # inherited from A

# super() calls
class Animal:
    def __init__(self, name, legs):
        self.name = name
        self.legs = legs

    def describe(self):
        return self.name + " has " + str(self.legs) + " legs"

class Dog(Animal):
    def __init__(self, name, breed):
        Animal.__init__(self, name, 4)
        self.breed = breed

    def describe(self):
        return Animal.describe(self) + " (" + self.breed + ")"

class Puppy(Dog):
    def __init__(self, name, breed):
        Dog.__init__(self, name, breed)
        self.is_puppy = True

    def describe(self):
        return Dog.describe(self) + " [puppy]"

d = Dog("Rex", "Labrador")
p = Puppy("Max", "Poodle")
print(d.describe())
print(p.describe())

# Multiple inheritance
class Flyer:
    def can_fly(self):
        return True
    def movement(self):
        return "flies"

class Swimmer:
    def can_swim(self):
        return True
    def movement(self):
        return "swims"

class Duck(Flyer, Swimmer):
    def __init__(self, name):
        self.name = name

duck = Duck("Donald")
print(duck.can_fly())
print(duck.can_swim())
print(duck.movement())  # MRO: Flyer first

# Method override with conditional super
class Logger:
    def log(self, msg):
        return "[LOG] " + msg

class TimedLogger(Logger):
    def log(self, msg):
        base = Logger.log(self, msg)
        return base + " @t=0"

class FilteredLogger(Logger):
    def __init__(self):
        self.blocked = []

    def log(self, msg):
        for word in self.blocked:
            if word in msg:
                return "[BLOCKED]"
        return Logger.log(self, msg)

tl = TimedLogger()
print(tl.log("hello"))

fl = FilteredLogger()
fl.blocked = ["secret"]
print(fl.log("normal message"))
print(fl.log("this is secret"))

# isinstance with inheritance
print(isinstance(d, Dog))
print(isinstance(d, Animal))
print(isinstance(p, Dog))
print(isinstance(p, Animal))
print(isinstance(p, Puppy))
print(isinstance(d, Puppy))

# Attribute inheritance
class Base:
    class_var = "base_value"

    def __init__(self):
        self.inst_var = "instance"

class Derived(Base):
    pass

obj = Derived()
print(obj.class_var)
print(obj.inst_var)

# Override class variable
class Parent:
    kind = "parent"
    def get_kind(self):
        return self.kind

class Child(Parent):
    kind = "child"

print(Parent().get_kind())
print(Child().get_kind())
