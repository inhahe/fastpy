"""Test native collections module support."""
from collections import Counter, defaultdict, deque, OrderedDict

# --- Counter ---
words = ["apple", "banana", "apple", "cherry", "banana", "apple"]
c = Counter(words)
print(c["apple"])     # 3
print(c["banana"])    # 2
print(c["cherry"])    # 1

# Counter.most_common
top = c.most_common(2)
print(len(top))       # 2

# Counter from empty
c2 = Counter()
c2.update(["a", "b", "a"])
print(c2["a"])        # 2

# --- defaultdict ---
dd_int = defaultdict(int)
dd_int["x"] += 1
dd_int["x"] += 1
dd_int["y"] += 1
print(dd_int["x"])    # 2
print(dd_int["y"])    # 1
print(len(dd_int))    # 2

# --- deque ---
dq = deque([1, 2, 3])
dq.append(4)
dq.appendleft(0)
print(len(dq))        # 5

val = dq.pop()
print(val)            # 4

val2 = dq.popleft()
print(val2)           # 0

dq.rotate(1)
print(len(dq))        # 3

# deque with maxlen
bounded = deque([1, 2, 3], maxlen=3)
bounded.append(4)     # evicts 1 from left
print(len(bounded))   # 3

# --- OrderedDict ---
od = OrderedDict()
od["first"] = 1
od["second"] = 2
od["third"] = 3
print(len(od))        # 3

print("All collections tests passed!")
