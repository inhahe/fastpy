# Bug 13: namedtuple repr shows plain tuple
from collections import namedtuple

Point = namedtuple("Point", ["x", "y"])
p = Point(3, 4)
print(p)
print(p.x)
print(p.y)
print(p[0])
print(p[1])
