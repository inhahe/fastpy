"""Test deque iteration and type improvements."""
from collections import deque

# Deque iteration
dq = deque([10, 20, 30, 40, 50])
total = 0
for x in dq:
    total += x
print(total)  # 150

# Counter iteration (keys)
from collections import Counter
c = Counter(["a", "b", "a", "c"])
count = 0
keys = c.keys()
for k in keys:
    count += 1
print(count)  # 3

print("iteration tests passed!")
