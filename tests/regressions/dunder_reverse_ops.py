# Regression: reverse operators (__radd__, __rsub__, __rmul__)

class V:
    def __init__(self, x):
        self.x = x

    def __add__(self, other):
        return V(self.x + other.x)

    def __radd__(self, other):
        return V(other + self.x)

    def __sub__(self, other):
        return V(self.x - other.x)

    def __rsub__(self, other):
        return V(other - self.x)

    def __mul__(self, other):
        return V(self.x * other.x)

    def __rmul__(self, other):
        return V(other * self.x)

    def __str__(self):
        return str(self.x)

a = V(5)

# Reverse add: int + V
print(10 + a)    # 15

# Reverse sub: int - V
print(20 - a)    # 15

# Reverse mul: int * V
print(3 * a)     # 15

# Forward still works
print(a + V(2))  # 7
