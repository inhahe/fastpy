# Regression: monomorphized class constructed via factory function.

class Value:
    def __init__(self, v):
        self.v = v


def make_int(x):
    return Value(x)


v1 = make_int(42)
print(v1.v)         # expected: 42
