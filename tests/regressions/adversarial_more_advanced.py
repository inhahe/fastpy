# Advanced patterns

# Map/filter
nums = [1, 2, 3, 4, 5]
squared = list(map(lambda x: x * x, nums))
print(squared)
evens = list(filter(lambda x: x % 2 == 0, nums))
print(evens)

# any/all
print(any([False, False, True]))
print(all([True, True, True]))
print(any([False, False, False]))
print(all([True, False, True]))

# Nested list manipulation
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
transposed = [[matrix[j][i] for j in range(3)] for i in range(3)]
for row in transposed:
    print(row)

# String methods
text = "Hello, World!"
print(text.count("l"))
print(text.upper())
print(text.replace("o", "0"))
print("abc" in text)
print("Hello" in text)

# (Skipped: dict comprehension with int keys. Our dict runtime only
#  supports string keys; {i: v for i in range(...)} with int i fails.)
