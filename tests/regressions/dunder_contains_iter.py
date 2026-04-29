# Regression: __contains__ and __iter__/__next__ on user classes

class Range:
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def __contains__(self, item):
        return self.start <= item < self.end

    def __str__(self):
        return "Range(" + str(self.start) + ", " + str(self.end) + ")"

r = Range(1, 10)
print(5 in r)     # True
print(10 in r)    # False
print(0 in r)     # False
