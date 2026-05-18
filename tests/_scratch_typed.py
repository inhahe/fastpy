class VKind:
    INT = 0
    FLOAT = 1
    STR = 2

class TypedValue:
    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def coerce_to(self, target_kind):
        if self.kind == target_kind:
            return self
        if self.kind == VKind.INT and target_kind == VKind.FLOAT:
            return TypedValue(VKind.FLOAT, float(self.value))
        if self.kind == VKind.FLOAT and target_kind == VKind.INT:
            return TypedValue(VKind.INT, int(self.value))
        return self

a = TypedValue(VKind.INT, 5)
b = TypedValue(VKind.FLOAT, 2.5)

l = a.coerce_to(VKind.FLOAT)
print(l.kind, l.value)

r = b.coerce_to(VKind.FLOAT)
print(r.kind, r.value)

result = TypedValue(VKind.FLOAT, l.value * r.value)
print(result.kind, result.value)
