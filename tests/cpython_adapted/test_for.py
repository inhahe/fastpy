# Adapted from CPython tests for for-loops
# Tests for loop semantics

# Basic for
for i in range(5):
    print(i)

# For over list
for x in [10, 20, 30, 40, 50]:
    print(x)

# For over string
for c in "python":
    print(c, end=" ")
print()

# For with break
for i in range(100):
    if i * i > 50:
        print("stopped at", i)
        break

# For with continue
result = []
for i in range(10):
    if i % 3 == 0:
        continue
    result.append(i)
print(result)

# For-else (no break)
for i in range(5):
    pass
else:
    print("loop completed")

# For-else (with break)
for i in range(10):
    if i == 5:
        break
else:
    print("this should not print")
print("ended at", i)

# Nested for
for i in range(1, 5):
    for j in range(1, 5):
        if i == j:
            print(i * j, end=" ")
    print()

# For with unpacking
points = [(1, 2), (3, 4), (5, 6)]
for x, y in points:
    print(x + y)

# For building result
squares = []
for i in range(10):
    squares.append(i * i)
print(squares)

# For with index tracking
data = ["a", "b", "c", "d", "e"]
for i in range(len(data)):
    print(i, data[i])

# For over dict
d = {"one": 1, "two": 2, "three": 3}
keys_sorted = sorted(d.keys())
for k in keys_sorted:
    print(k, d[k])

# For with accumulator pattern
def sum_list(lst):
    total = 0
    for x in lst:
        total += x
    return total

print(sum_list([1, 2, 3, 4, 5]))
print(sum_list(list(range(100))))

# For with max finding
def find_max(lst):
    best = lst[0]
    for x in lst:
        if x > best:
            best = x
    return best

print(find_max([3, 1, 4, 1, 5, 9, 2, 6]))
print(find_max([-5, -2, -8, -1]))

# For with filter + collect
def filter_positive(lst):
    result = []
    for x in lst:
        if x > 0:
            result.append(x)
    return result

print(filter_positive([1, -2, 3, -4, 5, -6]))

# Multiplication table
for i in range(1, 6):
    row = []
    for j in range(1, 6):
        row.append(i * j)
    print(row)

# String building
def repeat_str(s, n):
    result = ""
    for i in range(n):
        result += s
    return result

print(repeat_str("abc", 3))
print(repeat_str("x", 5))

# For with reversed
for x in reversed([1, 2, 3, 4, 5]):
    print(x, end=" ")
print()
