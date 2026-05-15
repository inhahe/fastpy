# Test any() and all() with generators and lists

lst = [1, 2, 3, 4, 5]

# any() with generator
print(any(x > 3 for x in lst))    # True
print(any(x > 10 for x in lst))   # False

# all() with generator
print(all(x > 0 for x in lst))    # True
print(all(x > 3 for x in lst))    # False

# any() and all() with lists
print(any([False, False, True]))   # True
print(any([False, False, False]))  # False
print(all([True, True, True]))     # True
print(all([True, False, True]))    # False

# Edge cases: empty sequences
print(any([]))                     # False
print(all([]))                     # True

# any/all with string truths
words = ["hello", "world", ""]
print(any(words))                  # True
print(all(words))                  # False

# Nested: any of all
groups = [[1, 2, 3], [0, 1, 2], [4, 5, 6]]
print(any(all(x > 0 for x in g) for g in groups))   # True
print(all(any(x > 2 for x in g) for g in groups))   # True

# Short-circuit behavior (side-effect free test)
nums = [0, 0, 1, 2, 3]
print(any(x != 0 for x in nums))   # True
print(all(x != 0 for x in nums))   # False
