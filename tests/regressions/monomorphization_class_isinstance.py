# Regression: isinstance with monomorphized classes.
# isinstance(obj, Processor) should be True regardless of which variant obj is.

class Box:
    def __init__(self, val):
        self.val = val

b1 = Box(5)
b2 = Box(2.5)

print(isinstance(b1, Box))    # expected: True
print(isinstance(b2, Box))    # expected: True

# Inside a function — obj param is an FV-typed generic
def check(x):
    return isinstance(x, Box)

print(check(b1))              # expected: True
print(check(b2))              # expected: True
