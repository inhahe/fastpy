# Adapted from CPython tests for special/dunder methods
# Tests __str__, __repr__, __eq__, __lt__, __len__, __add__, etc.

# __str__
class Fraction:
    def __init__(self, num, den):
        self.num = num
        self.den = den

    def __str__(self):
        if self.den == 1:
            return str(self.num)
        return str(self.num) + "/" + str(self.den)

    def __eq__(self, other):
        return self.num * other.den == other.num * self.den

    def __lt__(self, other):
        return self.num * other.den < other.num * self.den

    def __add__(self, other):
        new_num = self.num * other.den + other.num * self.den
        new_den = self.den * other.den
        return Fraction(new_num, new_den)

    def __mul__(self, other):
        return Fraction(self.num * other.num, self.den * other.den)

f1 = Fraction(1, 2)
f2 = Fraction(1, 3)
f3 = Fraction(2, 4)

print(f1)
print(f2)
print(f1 + f2)
print(f1 * f2)
print(f1 == f3)
print(f1 == f2)
print(f2 < f1)
print(f1 < f2)

# __len__ and __getitem__
class MyList:
    def __init__(self, items):
        self.items = items

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __contains__(self, item):
        for x in self.items:
            if x == item:
                return True
        return False

ml = MyList([10, 20, 30, 40, 50])
print(len(ml))
print(ml[0])
print(ml[2])
print(ml[-1])
print(30 in ml)
print(99 in ml)

# for iteration via __getitem__
result = []
for x in ml:
    result.append(x)
print(result)

# __iter__ and __next__
class Range:
    def __init__(self, start, stop):
        self.start = start
        self.stop = stop

    def __iter__(self):
        return RangeIter(self.start, self.stop)

class RangeIter:
    def __init__(self, current, stop):
        self.current = current
        self.stop = stop

    def __next__(self):
        if self.current >= self.stop:
            raise StopIteration
        val = self.current
        self.current += 1
        return val

    def __iter__(self):
        return self

print(list(Range(0, 5)))
print(list(Range(3, 8)))
print(sum(x for x in Range(1, 11)))

# __bool__
class Container:
    def __init__(self, items):
        self.items = items

    def __bool__(self):
        return len(self.items) > 0

    def __len__(self):
        return len(self.items)

empty = Container([])
full = Container([1, 2, 3])
print(bool(empty))
print(bool(full))
if full:
    print("has items")
if not empty:
    print("is empty")

# __neg__
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __str__(self):
        return "(" + str(self.x) + ", " + str(self.y) + ")"

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def __neg__(self):
        return Vector(-self.x, -self.y)

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

v1 = Vector(1, 2)
v2 = Vector(3, 4)
v3 = v1 + v2
print(v3)
print(-v1)
print(v1 + (-v2))
print(v1 == Vector(1, 2))
print(v1 == v2)
