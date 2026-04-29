# Regression: augmented assignment on object attributes
# self.attr += val for int, float, string, list, and OBJ dunders

class Counter:
    def __init__(self, n):
        self.count = n

# 1. Integer attributes
c = Counter(10)
c.count += 5
print(c.count)   # 15
c.count -= 3
print(c.count)   # 12
c.count *= 2
print(c.count)   # 24
c.count //= 5
print(c.count)   # 4

# 2. Float attributes
class Point:
    def __init__(self, x):
        self.x = x

p = Point(1.5)
p.x += 2.5
print(p.x)   # 4.0
p.x *= 3.0
print(p.x)   # 12.0
p.x -= 2.0
print(p.x)   # 10.0

# 3. String attributes
class Person:
    def __init__(self, name):
        self.name = name

p = Person("Alice")
p.name += " Smith"
print(p.name)   # Alice Smith

# 4. Multiple augmented assigns in sequence
c2 = Counter(0)
for i in range(5):
    c2.count += 1
print(c2.count)   # 5
