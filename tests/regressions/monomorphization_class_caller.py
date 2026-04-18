# Regression: monomorphized function called from a class method
# (the class method itself isn't monomorphized, but the function it
# calls should be).

def compute(x):
    return x * 2 + 1


class IntCalc:
    def __init__(self, val):
        self.val = val
    def run(self):
        return compute(self.val)


class FloatCalc:
    def __init__(self, val):
        self.val = val
    def run(self):
        return compute(self.val)


# The function `compute` should be monomorphized into compute__i and compute__d
# because IntCalc.run calls with int and FloatCalc.run calls with float.

ic = IntCalc(10)
print(ic.run())    # expected: 21 (int: 10*2+1)

fc = FloatCalc(3.5)
print(fc.run())    # expected: 8.0 (float: 3.5*2+1.0)

# Also test direct calls to verify both specs still work
print(compute(7))      # expected: 15
print(compute(2.5))    # expected: 6.0
