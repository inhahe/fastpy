# Benchmark: object allocation throughput.
# Creates N objects in a tight loop to measure the allocation fast path.

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

# Allocate 1M objects
n = 1000000
i = 0
while i < n:
    p = Point(i, i + 1)
    i = i + 1
print(p.x, p.y)
