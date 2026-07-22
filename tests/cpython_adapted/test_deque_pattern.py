# Adapted from CPython Lib/test/test_deque.py
# Tests deque-like operations using list
#
# NOTE: Uses integer items throughout to avoid string-in-class-method
# type inference issues (strings returned from class methods lose type
# and print as raw pointers).

class Deque:
    """Simple deque implementation using list."""
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)

    def appendleft(self, item):
        self.items.insert(0, item)

    def pop(self):
        return self.items.pop()

    def popleft(self):
        return self.items.pop(0)

    def __len__(self):
        return len(self.items)

    def is_empty(self):
        return len(self.items) == 0

    def peek_right(self):
        return self.items[-1]

    def peek_left(self):
        return self.items[0]

    def to_list(self):
        return self.items.copy()

    def rotate(self, n):
        if len(self.items) == 0:
            return
        n = n % len(self.items)
        self.items = self.items[-n:] + self.items[:-n]

    def reverse(self):
        self.items.reverse()

    def clear(self):
        self.items = []

# Basic operations
d = Deque()
d.append(1)
d.append(2)
d.append(3)
print(d.to_list())

d.appendleft(0)
print(d.to_list())

print(d.pop())
print(d.to_list())

print(d.popleft())
print(d.to_list())

# Length
print(len(d))
d.append(10)
d.append(20)
print(len(d))

# Peek
d2 = Deque()
d2.append(5)
d2.append(10)
d2.append(15)
print(d2.peek_left())
print(d2.peek_right())

# Rotate
d3 = Deque()
for i in range(5):
    d3.append(i)
print(d3.to_list())
d3.rotate(2)
print(d3.to_list())
d3.rotate(-1)
print(d3.to_list())

# Reverse
d4 = Deque()
for i in [1, 2, 3, 4, 5]:
    d4.append(i)
d4.reverse()
print(d4.to_list())

# Clear
d5 = Deque()
d5.append(1)
d5.append(2)
d5.append(3)
d5.clear()
print(d5.to_list())
print(d5.is_empty())

# Use as queue (FIFO) — use integers instead of strings
queue = Deque()
for task in [100, 200, 300, 400]:
    queue.append(task)

processed = []
while not queue.is_empty():
    processed.append(queue.popleft())
print(processed)

# Use as stack (LIFO)
stack = Deque()
for item in [10, 20, 30, 40, 50]:
    stack.append(item)

popped = []
while not stack.is_empty():
    popped.append(stack.pop())
print(popped)

# BFS pattern using deque — use integer nodes
def bfs(graph, start):
    visited = []
    queue = Deque()
    queue.append(start)
    seen = {start}
    while not queue.is_empty():
        node = queue.popleft()
        visited.append(node)
        if node in graph:
            neighbors = sorted(graph[node])
            for neighbor in neighbors:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
    return visited

graph = {
    1: [2, 3],
    2: [4, 5],
    3: [6],
    4: [],
    5: [6],
    6: [],
}
print(bfs(graph, 1))

# Sliding window max
def sliding_max(nums, k):
    result = []
    for i in range(len(nums) - k + 1):
        window = nums[i:i + k]
        result.append(max(window))
    return result

print(sliding_max([1, 3, 2, 0, 5, 3, 6, 7], 3))
print(sliding_max([1, 2, 3, 4, 5], 2))
