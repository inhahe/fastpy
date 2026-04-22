# Regression test for @ (matmul) operator (PEP 465)

class Vec:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __matmul__(self, other):
        # Dot product (returns int)
        return self.x * other.x + self.y * other.y

a = Vec(1, 2)
b = Vec(3, 4)
print(a @ b)       # 11

c = Vec(2, 0)
d = Vec(0, 3)
print(c @ d)       # 0

# @ with scalar result used in expression
result = (a @ b) + 1
print(result)      # 12

# Class where @ returns an object
class Matrix:
    def __init__(self, val):
        self.val = val

    def __matmul__(self, other):
        return Matrix(self.val * other.val)

    def __str__(self):
        return "Matrix(" + str(self.val) + ")"

m1 = Matrix(3)
m2 = Matrix(4)
print(m1 @ m2)     # Matrix(12)
