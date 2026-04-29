"""Test textwrap, glob, tempfile, heapq, bisect."""
import textwrap
import glob
import tempfile
import heapq
import bisect

# textwrap.dedent
text = "    hello\n    world"
d = textwrap.dedent(text)
print(d)  # "hello\nworld"

# glob.glob
files = glob.glob("compiler/*.py")
print(len(files) > 0)  # True

# tempfile.gettempdir
tmp = tempfile.gettempdir()
print(len(tmp) > 0)  # True

# heapq
h = [5, 3, 8, 1, 9, 2]
heapq.heapify(h)
smallest = heapq.heappop(h)
print(smallest)  # 1
next_sm = heapq.heappop(h)
print(next_sm)   # 2

heapq.heappush(h, 0)
print(heapq.heappop(h))  # 0

# bisect
sorted_list = [1, 3, 5, 7, 9, 11]
pos = bisect.bisect_left(sorted_list, 5)
print(pos)  # 2

bisect.insort(sorted_list, 6)
print(len(sorted_list))  # 7

print("new modules tests passed!")
