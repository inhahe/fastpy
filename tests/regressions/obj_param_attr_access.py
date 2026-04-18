# Regression: class instance passed as function parameter crashed on attr access
# Before fix: _analyze_call_sites didn't register class instances in var_types
# as "obj", so call-site analysis returned None for object arguments. This caused
# _declare_user_function to give the parameter static type i64 (instead of i8_ptr)
# and _emit_function_def to assign tag "int" (instead of "obj"). When the function
# body accessed p.x, _emit_attr_load got i64 but obj_get_fv expected i8*.
# Fix: (1) register class instances in var_types as "obj"
# (2) map "obj" to i8_ptr in param type resolution
# (3) map "obj" call_tag to "obj" variable tag
# (4) safety inttoptr in _emit_attr_load for robustness

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

def get_x(p):
    return p.x

def get_y(p):
    return p.y

def distance_sq(p1, p2):
    dx = p1.x - p2.x
    dy = p1.y - p2.y
    return dx * dx + dy * dy

a = Point(3, 4)
b = Point(0, 0)
print(get_x(a))
print(get_y(a))
print(distance_sq(a, b))
print(distance_sq(b, a))

# Object param with method call
class Counter:
    def __init__(self):
        self.count = 0

    def increment(self):
        self.count = self.count + 1

def bump(c, n):
    i = 0
    while i < n:
        c.increment()
        i = i + 1

c = Counter()
bump(c, 3)
print(c.count)
