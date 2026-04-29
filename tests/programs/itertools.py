"""Test native itertools module."""
from itertools import chain, repeat, product, combinations, permutations, accumulate, islice

# chain — must materialize to list for len/subscript
result = list(chain([1, 2, 3], [4, 5], [6]))
print(len(result))  # 6

# repeat
fives = list(repeat(5, 4))
print(len(fives))   # 4
print(fives[0])     # 5

# product (cartesian)
pairs = list(product([1, 2], [10, 20]))
print(len(pairs))   # 4 (2*2)

# combinations
combos = list(combinations([1, 2, 3, 4], 2))
print(len(combos))  # 6 (C(4,2) = 6)

# permutations
perms = list(permutations([1, 2, 3], 2))
print(len(perms))   # 6 (P(3,2) = 6)

# accumulate (running sum)
running = list(accumulate([1, 2, 3, 4, 5]))
print(running[4])   # 15 (1+2+3+4+5)

# islice
sliced = list(islice([10, 20, 30, 40, 50], 1, 4))
print(len(sliced))  # 3
print(sliced[0])    # 20

print("itertools tests passed!")
