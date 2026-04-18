# More common Python patterns

# Stack using list
stack = []
stack.append(1)
stack.append(2)
stack.append(3)
print(stack.pop())  # 3
print(stack.pop())  # 2
print(len(stack))   # 1

# Queue using list (pop from front is O(n) but works)
queue = []
queue.append(1)
queue.append(2)
queue.append(3)
# Python doesn't have deque but we can use del or slice
first = queue[0]
queue = queue[1:]
print(first, queue)

# Set operations (via dict of True) — skipped, int keys not supported.
# Alternative: use list + check
values = [1, 2, 2, 3, 3, 3, 4]
seen = []
for v in values:
    if v not in seen:
        seen.append(v)
print(sorted(seen))

# Two-pointer technique
def has_pair_sum(arr, target):
    arr_sorted = sorted(arr)
    lo, hi = 0, len(arr_sorted) - 1
    while lo < hi:
        s = arr_sorted[lo] + arr_sorted[hi]
        if s == target:
            return True
        elif s < target:
            lo = lo + 1
        else:
            hi = hi - 1
    return False

print(has_pair_sum([3, 1, 5, 7, 2], 8))   # True (3+5 or 1+7)
print(has_pair_sum([3, 1, 5, 7, 2], 100)) # False

# Counting word frequencies
text = "the quick brown fox jumps over the lazy dog the fox"
words = text.split()
count = {}
for w in words:
    if w in count:
        count[w] = count[w] + 1
    else:
        count[w] = 1

for k in sorted(count.keys()):
    print(k, count[k])
