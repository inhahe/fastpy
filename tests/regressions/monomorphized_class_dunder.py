# Regression: monomorphized class with __add__ / __mul__ returning new instances
# Previously crashed because:
# 1. _class_attr_slots not propagated to monomorphized variants → 0 slots allocated
# 2. _dcl_detect_method_ret_type didn't match original class name → __add__ returned double
# 3. Float BinOp fast path missed VKind.OBJ → v1 * 3.0 treated as scalar fmul
# 4. Dunder method params not in CSA → __mul__ scalar param tagged as INT

class Vector2D:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vector2D(self.x + other.x, self.y + other.y)

    def __mul__(self, scalar):
        return Vector2D(self.x * scalar, self.y * scalar)

    def length(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5

v1 = Vector2D(1.0, 2.0)
v2 = Vector2D(3.0, 4.0)
v3 = v1 + v2
print(v3.x)
print(v3.y)

v4 = v1 * 3.0
print(v4.x)
print(v4.y)

print(v2.length())
