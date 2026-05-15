# Nested list comprehensions

# 2D list: list of lists
result = [[j for j in range(3)] for i in range(2)]
print(result)

# Cartesian product style
result2 = [x * y for x in range(3) for y in range(3)]
print(result2)

# Nested with condition
result3 = [[j for j in range(i + 1)] for i in range(4)]
print(result3)

# Nested with outer variable used inside
result4 = [[i + j for j in range(3)] for i in range(3)]
print(result4)

# Flattened nested list
nested = [[1, 2], [3, 4], [5, 6]]
flat = [x for sublist in nested for x in sublist]
print(flat)
