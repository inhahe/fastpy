# Regression: max()/min() with key= kwarg, enumerate(..., start=N).

words = ["apple", "banana", "kiwi", "date"]
print(max(words, key=len))   # banana
print(min(words, key=len))   # kiwi

# With user function
def negate(x):
    return -x

nums = [3, 1, 4, 1, 5, 9, 2, 6]
print(max(nums, key=negate))   # 1 (smallest by negation)
print(min(nums, key=negate))   # 9

# Without key still works
print(max(nums))   # 9
print(min(nums))   # 1
print(max(words))  # kiwi
print(min(words))  # apple

# enumerate with start
for i, v in enumerate(["x", "y", "z"], start=10):
    print(i, v)

# enumerate without start
for i, v in enumerate(["a", "b", "c"]):
    print(i, v)
