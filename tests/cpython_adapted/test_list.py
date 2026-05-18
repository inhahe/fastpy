# Adapted from CPython Lib/test/test_list.py
# Tests list operations

# Basic construction
a = [1, 2, 3, 4, 5]
print(a)
print(len(a))

# Append
a.append(6)
print(a)

# Extend
a.extend([7, 8, 9])
print(a)

# Insert
b = [1, 2, 3]
b.insert(0, 0)
print(b)
b.insert(2, 99)
print(b)
b.insert(100, 100)  # beyond end
print(b)

# Pop
c = [1, 2, 3, 4, 5]
print(c.pop())
print(c)
print(c.pop(0))
print(c)
print(c.pop(1))
print(c)

# Remove
d = [1, 2, 3, 2, 1]
d.remove(2)
print(d)

# Index
e = [10, 20, 30, 40, 50]
print(e.index(30))
print(e.index(10))
print(e.index(50))

# Count
f = [1, 2, 3, 2, 1, 2, 3, 2]
print(f.count(2))
print(f.count(1))
print(f.count(5))

# Reverse
g = [1, 2, 3, 4, 5]
g.reverse()
print(g)

# Sort
h = [3, 1, 4, 1, 5, 9, 2, 6]
h.sort()
print(h)
h.sort(reverse=True)
print(h)

# Copy
i = [1, 2, 3]
j = i.copy()
j.append(4)
print(i)
print(j)

# Slicing
k = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
print(k[2:5])
print(k[:3])
print(k[7:])
print(k[::2])
print(k[1::2])
print(k[::-1])
print(k[8:2:-2])

# Slice assignment
m = [0, 1, 2, 3, 4, 5]
m[1:3] = [10, 20, 30]
print(m)
m[2:4] = []
print(m)
m[1:1] = [99, 98]
print(m)

# Multiplication
print([0] * 5)
print([1, 2] * 3)
print([1, 2, 3] * 0)

# Concatenation
print([1, 2] + [3, 4])
print([] + [1])
print([1] + [])

# Comparison
print([1, 2, 3] == [1, 2, 3])
print([1, 2, 3] == [1, 2, 4])
print([1, 2] < [1, 3])
print([1, 2, 3] < [1, 2, 3, 4])
print([1, 2, 4] > [1, 2, 3])

# In operator
print(3 in [1, 2, 3, 4, 5])
print(6 in [1, 2, 3, 4, 5])
print(3 not in [1, 2, 3, 4, 5])

# Nested lists
nested = [[1, 2], [3, 4], [5, 6]]
print(nested[1])
print(nested[0][1])
flat = []
for sub in nested:
    for x in sub:
        flat.append(x)
print(flat)

# List comprehension
squares = [x * x for x in range(10)]
print(squares)
evens = [x for x in range(20) if x % 2 == 0]
print(evens)

# Clear
n = [1, 2, 3, 4, 5]
n.clear()
print(n)
print(len(n))
