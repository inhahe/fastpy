# Regression: augmented assignment on objects (+=, -=, *=)

class Counter:
    def __init__(self, val):
        self.val = val

    def __iadd__(self, other):
        return Counter(self.val + other.val)

    def __isub__(self, other):
        return Counter(self.val - other.val)

    def __imul__(self, other):
        return Counter(self.val * other.val)

    def __str__(self):
        return str(self.val)

a = Counter(10)
b = Counter(3)

a += b
print(a)   # 13

a -= b
print(a)   # 10

a *= b
print(a)   # 30
