# Regression: dict comprehension with non-range iterators

# String keys from list
words = ["hello", "world", "hi"]
d1 = {w: len(w) for w in words}
print(d1)

# Int values from list
nums = [1, 2, 3, 4, 5]
d2 = {n: n*n for n in nums}
print(d2)

# With condition
d3 = {n: n*n for n in nums if n % 2 == 0}
print(d3)

# From dict iteration (keys)
src = {"a": 1, "b": 2, "c": 3}
d4 = {k: k.upper() for k in src}
print(d4)
