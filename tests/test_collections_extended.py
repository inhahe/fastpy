"""Extended collections tests: iteration, more methods."""
from collections import Counter, defaultdict, deque

# Counter: iteration via keys/values
c = Counter(["a", "b", "a", "c", "b", "a"])
keys = c.keys()
print(len(keys))      # 3

# Counter: elements
elems = c.elements()
print(len(elems))     # 6 (a*3 + b*2 + c*1)

# deque: extend and extendleft
dq = deque()
dq.extend([1, 2, 3])
dq.extendleft([10, 20])
print(len(dq))        # 5
# extendleft reverses: [20, 10, 1, 2, 3]
v = dq.popleft()
print(v)              # 20

# deque rotate
dq2 = deque([1, 2, 3, 4, 5])
dq2.rotate(2)         # [4, 5, 1, 2, 3]
v2 = dq2.popleft()
print(v2)             # 4

# deque clear
dq2.clear()
print(len(dq2))       # 0

# defaultdict with int: counting pattern
words = ["hello", "world", "hello", "foo", "world", "hello"]
freq = defaultdict(int)
i = 0
while i < len(words):
    freq[words[i]] += 1
    i += 1
print(freq["hello"])  # 3
print(freq["world"])  # 2
print(freq["foo"])    # 1

print("Extended tests passed!")
