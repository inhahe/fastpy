# Regression: map() and filter() with lambda

# Basic map with lambda
result = list(map(lambda x: x * 2, [1, 2, 3]))
print(result)           # [2, 4, 6]

# filter with lambda
result2 = list(filter(lambda x: x > 2, [1, 2, 3, 4]))
print(result2)          # [3, 4]

# map over empty list
result3 = list(map(lambda x: x + 1, []))
print(result3)          # []

# filter with all passing
result4 = list(filter(lambda x: x > 0, [1, 2, 3]))
print(result4)          # [1, 2, 3]

# filter with none passing
result5 = list(filter(lambda x: x > 10, [1, 2, 3]))
print(result5)          # []

# map with string transformation
words = ["hello", "world"]
result6 = list(map(lambda s: s.upper(), words))
print(result6)          # ['HELLO', 'WORLD']
