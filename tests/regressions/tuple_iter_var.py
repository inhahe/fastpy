# Regression: iterate over a tuple variable.

nums = (10, 20, 30)
total = 0
for n in nums:
    total = total + n
print(total)

# Also iterate over a tuple literal
sum2 = 0
for n in (1, 2, 3, 4):
    sum2 = sum2 + n
print(sum2)

# Unpacking during iteration
pairs = [(1, 2), (3, 4), (5, 6)]
for a, b in pairs:
    print(a + b)
