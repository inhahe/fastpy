class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def dist_sq(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy
p1 = Point(3, 4)
p2 = Point(7, 1)
total = 0
i = 0
while i < 1000000:
    total = total + p1.dist_sq(p2)
    i = i + 1
print(total)
