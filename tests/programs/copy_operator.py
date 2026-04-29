"""Test copy and operator modules."""
import copy
from operator import add, sub, mul

# copy.copy — shallow copy of list
original = [1, 2, 3, 4, 5]
copied = copy.copy(original)
copied.append(6)
print(len(original))  # 5 (unaffected)
print(len(copied))    # 6

# copy.deepcopy — deep copy of nested list
nested = [[1, 2], [3, 4]]
deep = copy.deepcopy(nested)
print(len(deep))      # 2

# copy.copy of dict
d = {"a": 1, "b": 2}
d2 = copy.copy(d)
print(len(d2))        # 2

# operator functions
print(add(3, 4))      # 7
print(sub(10, 3))     # 7
print(mul(6, 7))      # 42

# operator with reduce
from functools import reduce
nums = [1, 2, 3, 4, 5]
total = reduce(add, nums)
print(total)           # 15

product = reduce(mul, nums)
print(product)         # 120

print("copy/operator tests passed!")
