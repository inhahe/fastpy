# Regression: deep call chain with monomorphization propagation
# A(x) -> B(x) -> C(x), each called with both int and float

def C(x):
    return x * 3

def B(x):
    return C(x) + 1

def A(x):
    return B(x) + 1

print(A(5))      # expected: 17 (C=15, B=16, A=17)
print(A(2.0))    # expected: 8.0 (C=6.0, B=7.0, A=8.0)

# Method dispatch: each class instance uses a single type (no class sharing
# between int and float instances — that would require class monomorphization).
class IntProcessor:
    def __init__(self, x):
        self.x = x
    def process(self):
        return A(self.x)

class FloatProcessor:
    def __init__(self, x):
        self.x = x
    def process(self):
        return A(self.x)

p1 = IntProcessor(3)
print(p1.process())   # expected: 11 (C=9, B=10, A=11)

p2 = FloatProcessor(1.5)
print(p2.process())   # expected: 6.5 (C=4.5, B=5.5, A=6.5)
