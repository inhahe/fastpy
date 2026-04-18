# Regression: monomorphized class with methods returning self (fluent chain)
# and methods returning transformed values.

class Counter:
    def __init__(self, start):
        self.val = start
    def increment(self):
        self.val = self.val + 1
        return self
    def value(self):
        return self.val


# Int version
c1 = Counter(0)
c1.increment()
c1.increment()
print(c1.value())       # expected: 2

# Float version
c2 = Counter(0.5)
c2.increment()
print(c2.value())       # expected: 1.5

# Chained call
c3 = Counter(10)
c3.increment().increment().increment()
print(c3.value())       # expected: 13
