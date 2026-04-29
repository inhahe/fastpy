"""Test native random module."""
import random

# Seed for reproducibility
random.seed(42)

# random.random() — float in [0, 1)
r = random.random()
print(r > 0.0 and r < 1.0)  # True

# random.randint(a, b) — int in [a, b]
n = random.randint(1, 10)
print(n >= 1 and n <= 10)    # True

# random.randrange(start, stop)
m = random.randrange(0, 100)
print(m >= 0 and m < 100)   # True

# random.choice(list)
items = [10, 20, 30, 40, 50]
c = random.choice(items)
print(c >= 10 and c <= 50)   # True

# random.shuffle(list) — modifies in place
nums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
random.shuffle(nums)
# After shuffle, same elements but (usually) different order
total = 0
i = 0
while i < len(nums):
    total += nums[i]
    i += 1
print(total)  # 55 (sum preserved)

# random.sample(list, k) — k unique elements
s = random.sample([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3)
print(len(s))  # 3

# random.uniform(a, b) — float in [a, b]
u = random.uniform(5.0, 10.0)
print(u >= 5.0 and u <= 10.0)  # True

# random.gauss(mu, sigma)
g = random.gauss(0.0, 1.0)
print(g > -10.0 and g < 10.0)  # True (very likely)

print("random tests passed!")
