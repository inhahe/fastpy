# Regression: full set of comparison dunders and __abs__

class Val:
    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return self.x == other.x

    def __ne__(self, other):
        return self.x != other.x

    def __lt__(self, other):
        return self.x < other.x

    def __le__(self, other):
        return self.x <= other.x

    def __gt__(self, other):
        return self.x > other.x

    def __ge__(self, other):
        return self.x >= other.x

    def __abs__(self):
        return Val(abs(self.x))

    def __str__(self):
        return str(self.x)

a = Val(3)
b = Val(5)

# Equality
print(a == b)     # False
print(a == Val(3))  # True

# Inequality
print(a != b)     # True
print(a != Val(3))  # False

# Less than
print(a < b)      # True
print(b < a)      # False

# Less equal
print(a <= b)     # True
print(b <= a)     # False
print(a <= Val(3))  # True

# Greater than
print(a > b)      # False
print(b > a)      # True

# Greater equal
print(a >= b)     # False
print(b >= a)     # True
print(a >= Val(3))  # True

# Abs
print(abs(Val(-7)))  # 7
print(abs(Val(4)))   # 4
