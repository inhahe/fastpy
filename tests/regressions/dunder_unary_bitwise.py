# Regression: unary (__pos__, __invert__) and bitwise dunders

class Bits:
    def __init__(self, val):
        self.val = val

    def __and__(self, other):
        return Bits(self.val & other.val)

    def __or__(self, other):
        return Bits(self.val | other.val)

    def __xor__(self, other):
        return Bits(self.val ^ other.val)

    def __invert__(self):
        return Bits(~self.val)

    def __lshift__(self, other):
        return Bits(self.val << other.val)

    def __rshift__(self, other):
        return Bits(self.val >> other.val)

    def __pos__(self):
        return Bits(abs(self.val))

    def __neg__(self):
        return Bits(-self.val)

    def __str__(self):
        return str(self.val)

a = Bits(0b1100)  # 12
b = Bits(0b1010)  # 10

# Bitwise AND
print(a & b)    # 8

# Bitwise OR
print(a | b)    # 14

# Bitwise XOR
print(a ^ b)    # 6

# Invert
print(~Bits(0))  # -1

# Pos
print(+Bits(-5))  # 5

# Neg
print(-Bits(7))   # -7

# Shifts
print(Bits(1) << Bits(3))  # 8
print(Bits(16) >> Bits(2))  # 4
