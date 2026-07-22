# Adapted from CPython Lib/test/test_sort.py
# Tests sorting algorithms and sorted()

# Basic sort
a = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
a.sort()
print(a)

# Reverse sort
b = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
b.sort(reverse=True)
print(b)

# sorted() builtin
c = [5, 2, 8, 1, 9, 3, 7]
print(sorted(c))
print(sorted(c, reverse=True))
print(c)  # original unchanged

# Sort stability: equal elements maintain relative order
# (using tuples to test secondary order)
pairs = [(2, "b"), (1, "a"), (2, "a"), (1, "b"), (3, "a")]
pairs.sort()
print(pairs)

# Already sorted
d = [1, 2, 3, 4, 5]
d.sort()
print(d)

# Reverse sorted
e = [5, 4, 3, 2, 1]
e.sort()
print(e)

# All equal
f = [7, 7, 7, 7, 7]
f.sort()
print(f)

# Single element
g = [42]
g.sort()
print(g)

# Empty
h = []
h.sort()
print(h)

# Two elements
print(sorted([2, 1]))
print(sorted([1, 2]))

# Large range (verify correctness)
import_range = list(range(100, 0, -1))
import_range.sort()
print(import_range == list(range(1, 101)))

# Sort with key function
words = ["banana", "apple", "cherry", "date", "elderberry"]
words.sort(key=len)
print(words)

# Sorted with key
nums = [-5, -2, 0, 3, -1, 4, -3]
print(sorted(nums, key=abs))

# Sort strings
names = ["Charlie", "Alice", "Bob", "David", "Eve"]
names.sort()
print(names)

# Negative indices after sort
lst = [5, 3, 1, 4, 2]
lst.sort()
print(lst[-1])
print(lst[-2])

# Sort preserves type
mixed_ints = [0, -1, 1, -2, 2, -3, 3]
mixed_ints.sort()
print(mixed_ints)

# Descending via key
vals = [1, 2, 3, 4, 5]
vals.sort(key=lambda x: -x)
print(vals)
