# Adapted from CPython Lib/test/test_heapq.py
# Tests heap operations (pure Python fallback)

def _siftdown(heap, startpos, pos):
    newitem = heap[pos]
    while pos > startpos:
        parentpos = (pos - 1) // 2
        parent = heap[parentpos]
        if newitem < parent:
            heap[pos] = parent
            pos = parentpos
        else:
            break
    heap[pos] = newitem

def _siftup(heap, pos):
    endpos = len(heap)
    startpos = pos
    newitem = heap[pos]
    childpos = 2 * pos + 1
    while childpos < endpos:
        rightpos = childpos + 1
        if rightpos < endpos and not heap[childpos] < heap[rightpos]:
            childpos = rightpos
        heap[pos] = heap[childpos]
        pos = childpos
        childpos = 2 * pos + 1
    heap[pos] = newitem
    _siftdown(heap, startpos, pos)

def heappush(heap, item):
    heap.append(item)
    _siftdown(heap, 0, len(heap) - 1)

def heappop(heap):
    lastelt = heap.pop()
    if heap:
        returnitem = heap[0]
        heap[0] = lastelt
        _siftup(heap, 0)
        return returnitem
    return lastelt

def heapify(x):
    n = len(x)
    i = n // 2 - 1
    while i >= 0:
        _siftup(x, i)
        i = i - 1

# Basic push/pop
h = []
heappush(h, 5)
heappush(h, 3)
heappush(h, 7)
heappush(h, 1)
heappush(h, 9)
heappush(h, 2)

result = []
while len(h) > 0:
    result.append(heappop(h))
print(result)

# Heapify
data = [9, 7, 5, 3, 1, 8, 6, 4, 2, 0]
heapify(data)
sorted_data = []
while len(data) > 0:
    sorted_data.append(heappop(data))
print(sorted_data)

# Already sorted
already = [1, 2, 3, 4, 5]
heapify(already)
result2 = []
while len(already) > 0:
    result2.append(heappop(already))
print(result2)

# Reverse sorted
rev = [5, 4, 3, 2, 1]
heapify(rev)
result3 = []
while len(rev) > 0:
    result3.append(heappop(rev))
print(result3)

# Duplicates
dups = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
heapify(dups)
result4 = []
while len(dups) > 0:
    result4.append(heappop(dups))
print(result4)

# Single element
single = [42]
heapify(single)
print(heappop(single))

# Push then pop interleaved
h2 = []
heappush(h2, 10)
heappush(h2, 5)
print(heappop(h2))
heappush(h2, 3)
heappush(h2, 8)
print(heappop(h2))
print(heappop(h2))
heappush(h2, 1)
print(heappop(h2))
print(heappop(h2))
