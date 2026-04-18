# Regression: class methods returning bool printed 1/0 instead of True/False
# Before fix: (1) _declare_class didn't detect bool returns (Compare, BoolOp,
# Not, bool Constant) — methods defaulted to i64 return type.
# (2) Even after adding bool detection, the dispatch wrapper (obj_call_method*)
# always returns i64, so _wrap_for_print saw i64 and tagged as INT.
# Fix: (1) Added bool return detection to _declare_class and _declare_user_function
# (Compare, UnaryOp Not, bool Constant, BoolOp with all-bool operands).
# (2) Added method return type check in _wrap_for_print: when an object method
# call returns i32 (bool), truncate and wrap as BOOL.

class Range:
    def __init__(self, lo, hi):
        self.lo = lo
        self.hi = hi

    def contains(self, x):
        return x >= self.lo and x <= self.hi

    def is_single(self):
        return self.lo == self.hi

r = Range(1, 10)
print(r.contains(5))
print(r.contains(0))
print(r.contains(10))
print(r.is_single())

r2 = Range(5, 5)
print(r2.is_single())

# Method returning Compare directly
class Counter:
    def __init__(self):
        self.count = 0

    def increment(self):
        self.count = self.count + 1

    def is_zero(self):
        return self.count == 0

c = Counter()
print(c.is_zero())
c.increment()
print(c.is_zero())
