# Regression: int(obj) -> __int__, float(obj) -> __float__

class Val:
    def __init__(self, x):
        self.x = x

    def __int__(self):
        return self.x

    def __float__(self):
        return self.x * 1.0

    def __str__(self):
        return str(self.x)

v = Val(42)
print(int(v))     # 42
print(float(v))   # 42.0
