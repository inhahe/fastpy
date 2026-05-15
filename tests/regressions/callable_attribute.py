"""Regression test: callable attributes on user classes.

Previously, calling a function stored as an attribute (e.g., self.fn(x))
would crash with AttributeError because the dispatch looked for 'fn' in
the method table rather than loading it from the attribute slot. Fixed by
checking attribute slots when the method name isn't found in the class
method table.
"""


# Test 1: lambda stored as attribute, called inside method
class Transform:
    def __init__(self, fn):
        self.fn = fn
    def apply(self, x):
        return self.fn(x)

t = Transform(lambda x: x * 2)
print(t.apply(5))

# Test 2: user function stored as attribute
def double(x):
    return x * 2

class Processor:
    def __init__(self, fn):
        self.fn = fn
    def process(self, x):
        return self.fn(x)

p = Processor(double)
print(p.process(5))

# Test 3: callable attr called externally
def greet(name):
    print("Hello", name)

class Holder:
    def __init__(self, func):
        self.func = func

h = Holder(greet)
h.func("World")

# Test 4: callback pattern with None check
class EventHandler:
    def __init__(self):
        self.callback = None
    def set_callback(self, fn):
        self.callback = fn
    def fire(self):
        if self.callback is not None:
            self.callback()

def on_event():
    print("event fired")

e = EventHandler()
e.set_callback(on_event)
e.fire()

# Test 5: 2-arg callable attr
def add(a, b):
    return a + b

class Calculator:
    def __init__(self, op):
        self.op = op
    def compute(self, a, b):
        return self.op(a, b)

c = Calculator(add)
print(c.compute(3, 4))
