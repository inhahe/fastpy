# Test enumerate with default and start parameter

lst = ["a", "b", "c"]

# Default start=0
for i, v in enumerate(lst):
    print(i, v)
# 0 a
# 1 b
# 2 c

# start=1
for i, v in enumerate(lst, start=1):
    print(i, v)
# 1 a
# 2 b
# 3 c

# start=5
for i, v in enumerate(lst, 5):
    print(i, v)
# 5 a
# 6 b
# 7 c

# list(enumerate(...))
result = list(enumerate(["x", "y", "z"]))
print(result)
# [(0, 'x'), (1, 'y'), (2, 'z')]

result2 = list(enumerate(["x", "y", "z"], start=10))
print(result2)
# [(10, 'x'), (11, 'y'), (12, 'z')]

# enumerate over range
pairs = list(enumerate(range(3)))
print(pairs)
# [(0, 0), (1, 1), (2, 2)]

# enumerate in comprehension
doubled = [i * v for i, v in enumerate([1, 2, 3, 4])]
print(doubled)
# [0, 2, 6, 12]
