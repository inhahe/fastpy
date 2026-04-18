# Regression: method calls on nested object attributes, method return type
# for nested attr/method access, and nested class type inference.
#
# Before fix:
# - `self.inner.get()` raised "Unsupported method: .get()" (_is_obj_expr
#   rejected nested Attribute receivers)
# - `return self.pos.x` returned wrong type (return type detection didn't
#   handle nested attr access)
# - `return self.pos.method()` returned wrong type (no nested method lookup)
# - `_infer_object_class` returned None for nested Attribute nodes
#
# Fix: _class_obj_attr_types tracks which class each obj attr holds;
# _is_obj_expr, _infer_object_class, _emit_attr_load, and _declare_class
# return type detection all use this info.

# Nested method call with float-returning method
class Position:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def distance_from_origin(self):
        return (self.x * self.x + self.y * self.y) ** 0.5

class Entity:
    def __init__(self, name, pos):
        self.name = name
        self.pos = pos

    def distance(self):
        return self.pos.distance_from_origin()

    def describe(self):
        return self.name + " at " + str(self.pos.x) + "," + str(self.pos.y)

p = Position(3.0, 4.0)
e = Entity("Player", p)

# Direct nested attribute access
print(e.name)
print(e.pos.x)
print(e.pos.y)

# Nested attr access in method — returns float correctly
print(e.distance())
print(e.describe())

# Method call on nested attribute — direct at module level
print(e.pos.distance_from_origin())

# Method invocation through nested attribute
class Inner:
    def __init__(self, val):
        self.val = val

    def get(self):
        return self.val

class Outer:
    def __init__(self, inner):
        self.inner = inner

    def chained(self):
        return self.inner.get()

i = Inner(42)
o = Outer(i)
print(o.chained())
print(o.inner.get())
print(o.inner.val)

# Modifying nested object attributes through methods
class Counter:
    def __init__(self):
        self.value = 0

    def inc(self):
        self.value = self.value + 1

class Container:
    def __init__(self):
        self.counter = Counter()

cont = Container()
cont.counter.inc()
cont.counter.inc()
cont.counter.inc()
print(cont.counter.value)
