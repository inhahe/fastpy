# Regression: mixed return types in class hierarchy methods
# Bug: When base class method returns double and derived returns int,
# the dispatch uses obj_call_method0_double (from base's return type)
# which expects XMM0 but derived method returns in RAX (ABI mismatch).
# Fix: use i64 dispatch for mixed return types; obj_call_method0
# already handles double returns via return_tag check.

class Shape:
    def area(self):
        return 0.0

class Rectangle(Shape):
    def __init__(self, w, h):
        self.w = w
        self.h = h

    def area(self):
        return self.w * self.h

class Circle(Shape):
    def __init__(self, r):
        self.r = r

    def area(self):
        return 3.14159 * self.r * self.r

# Direct calls — these always worked
r = Rectangle(3, 4)
print(r.area())       # 12

c = Circle(5)
print(c.area())       # 78.53975

s = Shape()
print(s.area())       # 0.0

# Polymorphic calls — these were broken
shapes = [Rectangle(3, 4), Circle(5), Shape()]
for sh in shapes:
    print(sh.area())  # 12, 78.53975, 0.0
