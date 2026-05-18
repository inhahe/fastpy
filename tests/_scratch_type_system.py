# Simplified type system (like codegen's VKind/ValueType)
class VKind:
    INT = 0
    FLOAT = 1
    STR = 2
    BOOL = 3
    LIST = 4
    DICT = 5
    OBJ = 6
    NONE = 7

class TypedValue:
    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def is_numeric(self):
        return self.kind == VKind.INT or self.kind == VKind.FLOAT

    def is_ptr(self):
        return self.kind in (VKind.STR, VKind.LIST, VKind.DICT, VKind.OBJ)

    def coerce_to(self, target_kind):
        if self.kind == target_kind:
            return self
        if self.kind == VKind.INT and target_kind == VKind.FLOAT:
            return TypedValue(VKind.FLOAT, float(self.value))
        if self.kind == VKind.FLOAT and target_kind == VKind.INT:
            return TypedValue(VKind.INT, int(self.value))
        return self

# Type inference simulation
def infer_binop(left, right, op):
    if left.kind == VKind.FLOAT or right.kind == VKind.FLOAT:
        l = left.coerce_to(VKind.FLOAT)
        r = right.coerce_to(VKind.FLOAT)
        if op == "+":
            return TypedValue(VKind.FLOAT, l.value + r.value)
        elif op == "*":
            return TypedValue(VKind.FLOAT, l.value * r.value)
    else:
        if op == "+":
            return TypedValue(VKind.INT, left.value + right.value)
        elif op == "*":
            return TypedValue(VKind.INT, left.value * right.value)
    return TypedValue(VKind.NONE, 0)

# Tests
a = TypedValue(VKind.INT, 5)
b = TypedValue(VKind.FLOAT, 2.5)
c = TypedValue(VKind.INT, 3)

print(a.is_numeric(), a.is_ptr())
print(b.is_numeric(), b.is_ptr())

r1 = infer_binop(a, c, "+")
print(r1.kind, r1.value)

r2 = infer_binop(a, b, "*")
print(r2.kind, r2.value)

s = TypedValue(VKind.STR, "hello")
print(s.is_numeric(), s.is_ptr())
