# Adapted from CPython Lib/test/test_bisect.py
# Tests the bisect algorithm (pure Python fallback)

def bisect_right(a, x, lo=0, hi=None):
    if hi is None:
        hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo

def bisect_left(a, x, lo=0, hi=None):
    if hi is None:
        hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo

def insort_right(a, x, lo=0, hi=None):
    lo = bisect_right(a, x, lo, hi)
    a.insert(lo, x)

def insort_left(a, x, lo=0, hi=None):
    lo = bisect_left(a, x, lo, hi)
    a.insert(lo, x)

# Basic bisect_right
data = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
print(bisect_right(data, 0))   # 0
print(bisect_right(data, 1))   # 1
print(bisect_right(data, 5))   # 3
print(bisect_right(data, 6))   # 3
print(bisect_right(data, 19))  # 10
print(bisect_right(data, 20))  # 10

# Basic bisect_left
print(bisect_left(data, 0))    # 0
print(bisect_left(data, 1))    # 0
print(bisect_left(data, 5))    # 2
print(bisect_left(data, 6))    # 3
print(bisect_left(data, 19))   # 9
print(bisect_left(data, 20))   # 10

# Duplicates
dups = [1, 2, 2, 2, 3, 4, 4, 5]
print(bisect_left(dups, 2))    # 1
print(bisect_right(dups, 2))   # 4
print(bisect_left(dups, 4))    # 5
print(bisect_right(dups, 4))   # 7

# insort
lst = []
for x in [5, 2, 8, 1, 9, 3, 7, 4, 6, 0]:
    insort_right(lst, x)
print(lst)

lst2 = []
for x in [10, 5, 15, 3, 12, 7, 1]:
    insort_left(lst2, x)
print(lst2)

# Empty list
print(bisect_left([], 5))
print(bisect_right([], 5))

# Single element
print(bisect_left([5], 3))
print(bisect_left([5], 5))
print(bisect_left([5], 7))
print(bisect_right([5], 3))
print(bisect_right([5], 5))
print(bisect_right([5], 7))

# With lo/hi bounds
arr = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
print(bisect_left(arr, 5, 2, 8))   # within bounds
print(bisect_right(arr, 5, 2, 8))  # within bounds
print(bisect_left(arr, 5, 6, 9))   # after target
print(bisect_right(arr, 5, 0, 3))  # before target
