"""
Artificial, floating point-heavy benchmark originally used by Factor.
Adapted: removed pyperf, __slots__, __repr__, and string formatting.
"""

import time
import math


POINTS = 100000


class Point:

    def __init__(self, i):
        self.x = math.sin(i)
        self.y = math.cos(i) * 3
        self.z = (self.x * self.x) / 2

    def normalize(self):
        x = self.x
        y = self.y
        z = self.z
        norm = math.sqrt(x * x + y * y + z * z)
        self.x = self.x / norm
        self.y = self.y / norm
        self.z = self.z / norm

    def maximize(self, other):
        if other.x > self.x:
            self.x = other.x
        if other.y > self.y:
            self.y = other.y
        if other.z > self.z:
            self.z = other.z
        return self


def find_max(points):
    next_p = points[0]
    i = 1
    while i < len(points):
        next_p = next_p.maximize(points[i])
        i += 1
    return next_p


def benchmark(n):
    points = []
    i = 0
    while i < n:
        points.append(Point(i))
        i += 1
    for p in points:
        p.normalize()
    return find_max(points)


LOOPS = 15

t0 = time.perf_counter()
loop_i = 0
while loop_i < LOOPS:
    result = benchmark(POINTS)
    loop_i += 1
elapsed = time.perf_counter() - t0
print(result.x)
print(result.y)
print(result.z)
print("elapsed ms=")
print(elapsed * 1000)
