# Regression: sum() with float elements (dict.values(), list of floats)
# Bug: sum() always used integer accumulation (i64 add), so float
# elements had their bit patterns added as integers → garbage results.
# Fix: detect float elements and use double accumulator with fadd.

# Case 1: sum of dict values (floats)
prices = {"apple": 1.5, "banana": 0.75, "cherry": 3.0}
total = sum(prices.values())
print(total)

# Case 2: average of dict values
average = total / len(prices)
print(round(average, 2))

# Case 3: sum of float list
nums = [1.5, 2.5, 3.5]
print(sum(nums))

# Case 4: sum of int list (should still work)
ints = [1, 2, 3, 4, 5]
print(sum(ints))

# Case 5: sum with start value
print(sum(ints, 10))

# Case 6: sum of empty list
print(sum([]))

# Case 7: sum with float start value on int list
print(sum([1, 2, 3], 0.0))

# Case 8: map(float, ints) — int-to-float conversion
nums = [1, 2, 3, 4, 5]
print(list(map(float, nums)))
