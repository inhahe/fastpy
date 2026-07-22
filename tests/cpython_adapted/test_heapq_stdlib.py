# Adapted from CPython Lib/heapq.py — stdlib heap algorithms
# Tests the heap queue functions compiled by fastpy.
#
# The full CPython heapq module includes merge(), nlargest(), nsmallest()
# which use generators, tuples-as-heap-elements, and function aliasing.
# These trigger compiler limitations, so we test the core heap operations
# (the actual algorithms) which are pure functions on integer lists.
#
# Core functions inlined verbatim from CPython Lib/heapq.py with only
# the docstrings shortened and the `continue` replaced by explicit else.

# ======================================================================
# CPython heap internals — the actual algorithms
# ======================================================================

def _siftdown(heap, startpos, pos):
    newitem = heap[pos]
    while pos > startpos:
        parentpos = (pos - 1) >> 1
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

def _siftdown_max(heap, startpos, pos):
    newitem = heap[pos]
    while pos > startpos:
        parentpos = (pos - 1) >> 1
        parent = heap[parentpos]
        if parent < newitem:
            heap[pos] = parent
            pos = parentpos
        else:
            break
    heap[pos] = newitem

def _siftup_max(heap, pos):
    endpos = len(heap)
    startpos = pos
    newitem = heap[pos]
    childpos = 2 * pos + 1
    while childpos < endpos:
        rightpos = childpos + 1
        if rightpos < endpos and not heap[rightpos] < heap[childpos]:
            childpos = rightpos
        heap[pos] = heap[childpos]
        pos = childpos
        childpos = 2 * pos + 1
    heap[pos] = newitem
    _siftdown_max(heap, startpos, pos)

# ======================================================================
# CPython public API — core operations (verbatim from Lib/heapq.py)
# ======================================================================

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

def heapreplace(heap, item):
    returnitem = heap[0]
    heap[0] = item
    _siftup(heap, 0)
    return returnitem

def heappushpop(heap, item):
    if heap and heap[0] < item:
        item, heap[0] = heap[0], item
        _siftup(heap, 0)
    return item

def heapify(x):
    n = len(x)
    i = n // 2 - 1
    while i >= 0:
        _siftup(x, i)
        i = i - 1

def _heappop_max(heap):
    lastelt = heap.pop()
    if heap:
        returnitem = heap[0]
        heap[0] = lastelt
        _siftup_max(heap, 0)
        return returnitem
    return lastelt

def _heapify_max(x):
    n = len(x)
    i = n // 2 - 1
    while i >= 0:
        _siftup_max(x, i)
        i = i - 1

# ======================================================================
# Heap invariant checker
# ======================================================================

def _check_heap_invariant(heap):
    n = len(heap)
    i = 0
    while i < n:
        left = 2 * i + 1
        right = 2 * i + 2
        if left < n and heap[i] > heap[left]:
            return False
        if right < n and heap[i] > heap[right]:
            return False
        i = i + 1
    return True

def _check_maxheap_invariant(heap):
    n = len(heap)
    i = 0
    while i < n:
        left = 2 * i + 1
        right = 2 * i + 2
        if left < n and heap[i] < heap[left]:
            return False
        if right < n and heap[i] < heap[right]:
            return False
        i = i + 1
    return True

# ======================================================================
# Tests
# ======================================================================

def test_heappush_heappop():
    h = []
    heappush(h, 5)
    heappush(h, 3)
    heappush(h, 7)
    heappush(h, 1)
    heappush(h, 9)
    heappush(h, 2)
    ok = _check_heap_invariant(h)
    result = []
    while len(h) > 0:
        result.append(heappop(h))
    ok2 = (result == [1, 2, 3, 5, 7, 9])
    if ok and ok2:
        print("TestHeap.test_heappush_heappop: PASS")
    else:
        print("TestHeap.test_heappush_heappop: FAIL -", ok, ok2, result)

def test_heapify():
    data = [9, 7, 5, 3, 1, 8, 6, 4, 2, 0]
    heapify(data)
    ok1 = _check_heap_invariant(data)
    sorted_data = []
    while len(data) > 0:
        sorted_data.append(heappop(data))
    ok2 = (sorted_data == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    # Already sorted input
    already = [1, 2, 3, 4, 5]
    heapify(already)
    ok3 = _check_heap_invariant(already)
    result2 = []
    while len(already) > 0:
        result2.append(heappop(already))
    ok4 = (result2 == [1, 2, 3, 4, 5])
    # Reverse sorted input
    rev = [5, 4, 3, 2, 1]
    heapify(rev)
    ok5 = _check_heap_invariant(rev)
    result3 = []
    while len(rev) > 0:
        result3.append(heappop(rev))
    ok6 = (result3 == [1, 2, 3, 4, 5])
    if ok1 and ok2 and ok3 and ok4 and ok5 and ok6:
        print("TestHeap.test_heapify: PASS")
    else:
        print("TestHeap.test_heapify: FAIL")

def test_heapify_duplicates():
    dups = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
    heapify(dups)
    ok1 = _check_heap_invariant(dups)
    result = []
    while len(dups) > 0:
        result.append(heappop(dups))
    ok2 = (result == [1, 1, 2, 3, 3, 4, 5, 5, 6, 9])
    if ok1 and ok2:
        print("TestHeap.test_heapify_duplicates: PASS")
    else:
        print("TestHeap.test_heapify_duplicates: FAIL -", result)

def test_heapreplace():
    h = [1, 3, 5, 7, 9]
    heapify(h)
    old = heapreplace(h, 4)
    ok1 = (old == 1)
    ok2 = _check_heap_invariant(h)
    ok3 = (len(h) == 5)
    # Replace with something smaller than current min
    h2 = [2, 4, 6]
    heapify(h2)
    old2 = heapreplace(h2, 1)
    ok4 = (old2 == 2)
    ok5 = (h2[0] == 1)
    ok6 = _check_heap_invariant(h2)
    if ok1 and ok2 and ok3 and ok4 and ok5 and ok6:
        print("TestHeap.test_heapreplace: PASS")
    else:
        print("TestHeap.test_heapreplace: FAIL")

def test_heappushpop():
    h = [1, 3, 5, 7, 9]
    heapify(h)
    # Push something larger than min — should pop min
    r = heappushpop(h, 4)
    ok1 = (r == 1)
    ok2 = _check_heap_invariant(h)
    ok3 = (len(h) == 5)
    # Push something smaller than min — should return it immediately
    h2 = [10, 20, 30]
    heapify(h2)
    r2 = heappushpop(h2, 5)
    ok4 = (r2 == 5)
    ok5 = (h2[0] == 10)
    ok6 = (len(h2) == 3)
    # Empty heap
    h3 = []
    r3 = heappushpop(h3, 42)
    ok7 = (r3 == 42)
    ok8 = (len(h3) == 0)
    if ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8:
        print("TestHeap.test_heappushpop: PASS")
    else:
        print("TestHeap.test_heappushpop: FAIL")

def test_maxheap():
    data = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
    _heapify_max(data)
    ok1 = _check_maxheap_invariant(data)
    result = []
    while len(data) > 0:
        result.append(_heappop_max(data))
    ok2 = (result == [9, 6, 5, 5, 4, 3, 3, 2, 1, 1])
    if ok1 and ok2:
        print("TestHeap.test_maxheap: PASS")
    else:
        print("TestHeap.test_maxheap: FAIL -", result)

def test_heapsort():
    data = [7, 2, 9, 4, 1, 6, 3, 8, 5, 0]
    heapify(data)
    result = []
    while len(data) > 0:
        result.append(heappop(data))
    ok = (result == sorted([7, 2, 9, 4, 1, 6, 3, 8, 5, 0]))
    # Large-ish dataset
    data2 = []
    i = 100
    while i >= 0:
        data2.append(i)
        i = i - 1
    heapify(data2)
    result2 = []
    while len(data2) > 0:
        result2.append(heappop(data2))
    ok2 = True
    j = 0
    while j < len(result2) - 1:
        if result2[j] > result2[j + 1]:
            ok2 = False
        j = j + 1
    ok3 = (len(result2) == 101)
    if ok and ok2 and ok3:
        print("TestHeap.test_heapsort: PASS")
    else:
        print("TestHeap.test_heapsort: FAIL")

def test_push_pop_interleaved():
    h = []
    heappush(h, 10)
    heappush(h, 5)
    r1 = heappop(h)
    ok1 = (r1 == 5)
    heappush(h, 3)
    heappush(h, 8)
    r2 = heappop(h)
    ok2 = (r2 == 3)
    r3 = heappop(h)
    ok3 = (r3 == 8)
    heappush(h, 1)
    r4 = heappop(h)
    ok4 = (r4 == 1)
    r5 = heappop(h)
    ok5 = (r5 == 10)
    if ok1 and ok2 and ok3 and ok4 and ok5:
        print("TestHeap.test_push_pop_interleaved: PASS")
    else:
        print("TestHeap.test_push_pop_interleaved: FAIL")

def test_single_element():
    h = [42]
    heapify(h)
    ok1 = (heappop(h) == 42)
    ok2 = (len(h) == 0)
    # heappushpop on single element
    h2 = [5]
    r = heappushpop(h2, 3)
    ok3 = (r == 3)
    ok4 = (h2[0] == 5)
    r2 = heappushpop(h2, 10)
    ok5 = (r2 == 5)
    ok6 = (h2[0] == 10)
    if ok1 and ok2 and ok3 and ok4 and ok5 and ok6:
        print("TestHeap.test_single_element: PASS")
    else:
        print("TestHeap.test_single_element: FAIL")

# ======================================================================
# Run all tests
# ======================================================================

try:
    test_heappush_heappop()
except Exception as _e:
    print("TestHeap.test_heappush_heappop: FAIL -", _e)
try:
    test_heapify()
except Exception as _e:
    print("TestHeap.test_heapify: FAIL -", _e)
try:
    test_heapify_duplicates()
except Exception as _e:
    print("TestHeap.test_heapify_duplicates: FAIL -", _e)
try:
    test_heapreplace()
except Exception as _e:
    print("TestHeap.test_heapreplace: FAIL -", _e)
try:
    test_heappushpop()
except Exception as _e:
    print("TestHeap.test_heappushpop: FAIL -", _e)
try:
    test_maxheap()
except Exception as _e:
    print("TestHeap.test_maxheap: FAIL -", _e)
try:
    test_heapsort()
except Exception as _e:
    print("TestHeap.test_heapsort: FAIL -", _e)
try:
    test_push_pop_interleaved()
except Exception as _e:
    print("TestHeap.test_push_pop_interleaved: FAIL -", _e)
try:
    test_single_element()
except Exception as _e:
    print("TestHeap.test_single_element: FAIL -", _e)
