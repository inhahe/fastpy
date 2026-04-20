"""Test typing and abc module support."""
from typing import Optional, List, Dict
from abc import ABC, abstractmethod
from functools import reduce

# typing imports are no-ops
x: Optional[int] = 42
y: List[int] = [1, 2, 3]
print(x)        # 42
print(len(y))   # 3

# ABC with abstractmethod
class Shape(ABC):
    @abstractmethod
    def area(self):
        pass

class Circle(Shape):
    def __init__(self, radius):
        self.radius = radius

    def area(self):
        return 3.14159 * self.radius * self.radius

c = Circle(5)
print(c.area())   # ~78.5

# functools.reduce
nums = [1, 2, 3, 4, 5]
def add(a, b):
    return a + b

total = reduce(add, nums)
print(total)      # 15

total2 = reduce(add, nums, 10)
print(total2)     # 25

print("typing/abc/functools tests passed!")
