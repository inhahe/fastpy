# Test: class attributes used in list/tuple construction
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def as_tuple(self):
        return (self.x, self.y)
    def as_list(self):
        return [self.x, self.y]

p = Point(3, 4)
print(p.as_tuple())
print(p.as_list())

class Named:
    def __init__(self, name, val):
        self.name = name
        self.val = val
    def pair(self):
        return (self.name, self.val)

n = Named("hello", 42)
print(n.pair())
