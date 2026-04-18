# Regression: class monomorphization — same class used with both int and
# float constructor args. Phase 5 class mono generates Processor__i and
# Processor__d variants.

def compute(x):
    return x * 2 + 1


class Processor:
    def __init__(self, x):
        self.x = x
    def process(self):
        return compute(self.x)


p1 = Processor(3)
print(p1.process())    # expected: 7 (compute__i: 3*2+1)

p2 = Processor(1.5)
print(p2.process())    # expected: 4.0 (compute__d: 1.5*2+1.0)

# Direct calls still work
print(compute(7))      # expected: 15
print(compute(2.5))    # expected: 6.0
