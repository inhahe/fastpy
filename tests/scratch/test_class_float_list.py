# Test: class with float attrs used in list/tuple
class Vec2:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def to_list(self):
        return [self.x, self.y]
    def to_tuple(self):
        return (self.x, self.y)

v = Vec2(1.5, 2.5)
print(v.to_list())
print(v.to_tuple())

v2 = Vec2(3, 4)
print(v2.to_list())
print(v2.to_tuple())
