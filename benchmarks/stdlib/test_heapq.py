"""heapq stdlib tests — inlined source + ported CPython test suite.

Covers: heappush, heappop, heapify, heapreplace, heappushpop (min-heap),
        heappush_max, heappop_max, heapify_max, heapreplace_max,
        heappushpop_max (max-heap), and internal _siftdown/_siftup functions.
Skipped: merge (generators), nlargest/nsmallest (iterators, key=), key= params.
"""

# ---------------------------------------------------------------------------
# Inlined heapq source (CPython 3.14 pure-Python fallback)
# ---------------------------------------------------------------------------

def _siftdown(heap, startpos, pos):
    newitem = heap[pos]
    while pos > startpos:
        parentpos = (pos - 1) >> 1
        parent = heap[parentpos]
        if newitem < parent:
            heap[pos] = parent
            pos = parentpos
            continue
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
            continue
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
    # Use nested ifs instead of `and` — compiler doesn't short-circuit
    # `heap and heap[0] < item` (evaluates heap[0] even when heap is empty).
    if heap:
        if heap[0] < item:
            tmp = heap[0]
            heap[0] = item
            item = tmp
            _siftup(heap, 0)
    return item

def heapify(x):
    n = len(x)
    for i in reversed(range(n // 2)):
        _siftup(x, i)

def heappop_max(heap):
    lastelt = heap.pop()
    if heap:
        returnitem = heap[0]
        heap[0] = lastelt
        _siftup_max(heap, 0)
        return returnitem
    return lastelt

def heapreplace_max(heap, item):
    returnitem = heap[0]
    heap[0] = item
    _siftup_max(heap, 0)
    return returnitem

def heappush_max(heap, item):
    heap.append(item)
    _siftdown_max(heap, 0, len(heap) - 1)

def heappushpop_max(heap, item):
    # Use nested ifs instead of `and` — compiler doesn't short-circuit
    # `heap and item < heap[0]` (evaluates heap[0] even when heap is empty).
    if heap:
        if item < heap[0]:
            tmp = heap[0]
            heap[0] = item
            item = tmp
            _siftup_max(heap, 0)
    return item

def heapify_max(x):
    n = len(x)
    for i in reversed(range(n // 2)):
        _siftup_max(x, i)

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_pass_count = 0
_fail_count = 0
_group_pass = 0
_group_fail = 0

def _assert_eq(actual, expected, msg=""):
    global _pass_count, _fail_count, _group_pass, _group_fail
    if actual == expected:
        _pass_count = _pass_count + 1
        _group_pass = _group_pass + 1
    else:
        _fail_count = _fail_count + 1
        _group_fail = _group_fail + 1
        if msg:
            print("FAIL:", msg, "got", actual, "expected", expected)
        else:
            print("FAIL: got", actual, "expected", expected)

def _assert_list_eq(actual, expected, msg=""):
    """Compare two lists. Separate function to avoid mixed int/list call sites."""
    global _pass_count, _fail_count, _group_pass, _group_fail
    if actual == expected:
        _pass_count = _pass_count + 1
        _group_pass = _group_pass + 1
    else:
        _fail_count = _fail_count + 1
        _group_fail = _group_fail + 1
        if msg:
            print("FAIL:", msg, "got", actual, "expected", expected)
        else:
            print("FAIL: got", actual, "expected", expected)

def _assert_true(cond, msg=""):
    global _pass_count, _fail_count, _group_pass, _group_fail
    if cond:
        _pass_count = _pass_count + 1
        _group_pass = _group_pass + 1
    else:
        _fail_count = _fail_count + 1
        _group_fail = _group_fail + 1
        if msg:
            print("FAIL:", msg)
        else:
            print("FAIL: assertion false")

def _start_group(name):
    global _group_pass, _group_fail
    _group_pass = 0
    _group_fail = 0

def _end_group(name):
    total = _group_pass + _group_fail
    print("  " + name + ": " + str(_group_pass) + "/" + str(total))

# ---------------------------------------------------------------------------
# Heap invariant checkers
# ---------------------------------------------------------------------------

def _check_heap(heap):
    n = len(heap)
    for i in range(n):
        left = 2 * i + 1
        right = 2 * i + 2
        if left < n and heap[i] > heap[left]:
            return False
        if right < n and heap[i] > heap[right]:
            return False
    return True

def _check_maxheap(heap):
    n = len(heap)
    for i in range(n):
        left = 2 * i + 1
        right = 2 * i + 2
        if left < n and heap[i] < heap[left]:
            return False
        if right < n and heap[i] < heap[right]:
            return False
    return True

# ---------------------------------------------------------------------------
# Test: heappush basic
# ---------------------------------------------------------------------------

def test_heappush_basic():
    _start_group("heappush_basic")
    h = []
    heappush(h, 5)
    _assert_list_eq(h, [5], "push to empty")
    heappush(h, 3)
    _assert_eq(h[0], 3, "push smaller becomes root")
    _assert_true(_check_heap(h), "invariant after 2 pushes")
    heappush(h, 7)
    _assert_eq(h[0], 3, "push larger keeps root")
    _assert_true(_check_heap(h), "invariant after 3 pushes")
    heappush(h, 1)
    _assert_eq(h[0], 1, "push smallest becomes new root")
    _assert_true(_check_heap(h), "invariant after 4 pushes")
    _assert_eq(len(h), 4, "length after 4 pushes")
    _end_group("heappush_basic")

test_heappush_basic()

# ---------------------------------------------------------------------------
# Test: heappop basic — split to avoid list reassignment
# ---------------------------------------------------------------------------

def test_heappop_sequence():
    _start_group("heappop_sequence")
    h = [1, 3, 5, 7]
    heapify(h)
    v = heappop(h)
    _assert_eq(v, 1, "pop returns smallest")
    _assert_true(_check_heap(h), "invariant after pop")
    v = heappop(h)
    _assert_eq(v, 3, "pop returns next smallest")
    _assert_true(_check_heap(h), "invariant after 2nd pop")
    v = heappop(h)
    _assert_eq(v, 5, "pop returns next")
    v = heappop(h)
    _assert_eq(v, 7, "pop returns last")
    _assert_eq(len(h), 0, "empty after all pops")
    _end_group("heappop_sequence")

def test_heappop_single():
    _start_group("heappop_single")
    h = [42]
    v = heappop(h)
    _assert_eq(v, 42, "pop single element")
    _assert_eq(len(h), 0, "empty after single pop")
    _end_group("heappop_single")

test_heappop_sequence()
test_heappop_single()

# ---------------------------------------------------------------------------
# Test: heapify — one function per case (already split)
# ---------------------------------------------------------------------------

def test_heapify_sorted():
    _start_group("heapify_sorted")
    h = [1, 2, 3, 4, 5]
    heapify(h)
    _assert_true(_check_heap(h), "heapify sorted")
    _assert_eq(h[0], 1, "heapify sorted root")
    _end_group("heapify_sorted")

def test_heapify_reverse():
    _start_group("heapify_reverse")
    h = [5, 4, 3, 2, 1]
    heapify(h)
    _assert_true(_check_heap(h), "heapify reverse")
    _assert_eq(h[0], 1, "heapify reverse root")
    _end_group("heapify_reverse")

def test_heapify_random():
    _start_group("heapify_random")
    h = [3, 1, 4, 1, 5, 9, 2, 6]
    heapify(h)
    _assert_true(_check_heap(h), "heapify random")
    _assert_eq(h[0], 1, "heapify random root")
    _end_group("heapify_random")

def test_heapify_single():
    _start_group("heapify_single")
    h = [42]
    heapify(h)
    _assert_true(_check_heap(h), "heapify single")
    _assert_eq(h[0], 42, "heapify single root")
    _end_group("heapify_single")

def test_heapify_same():
    _start_group("heapify_same")
    h = [5, 5, 5, 5, 5]
    heapify(h)
    _assert_true(_check_heap(h), "heapify all same")
    _assert_eq(h[0], 5, "heapify all same root")
    _end_group("heapify_same")

def test_heapify_two():
    _start_group("heapify_two")
    h = [2, 1]
    heapify(h)
    _assert_true(_check_heap(h), "heapify two")
    _assert_eq(h[0], 1, "heapify two root")
    _end_group("heapify_two")

def test_heapify_100():
    _start_group("heapify_100")
    h = []
    v = 73
    for i in range(100):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        h.append(v % 1000)
    heapify(h)
    _assert_true(_check_heap(h), "heapify 100")
    _end_group("heapify_100")

def test_heapify_1000():
    _start_group("heapify_1000")
    h = []
    v = 42
    for i in range(1000):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        h.append(v % 10000)
    heapify(h)
    _assert_true(_check_heap(h), "heapify 1000")
    _end_group("heapify_1000")

test_heapify_sorted()
test_heapify_reverse()
test_heapify_random()
test_heapify_single()
test_heapify_same()
test_heapify_two()
test_heapify_100()
test_heapify_1000()

# ---------------------------------------------------------------------------
# Test: heapreplace — split into 3 to avoid list reassignment
# ---------------------------------------------------------------------------

def test_heapreplace_basic():
    _start_group("heapreplace_basic")
    h = [1, 3, 5, 7, 9]
    heapify(h)
    old = heapreplace(h, 4)
    _assert_eq(old, 1, "heapreplace returns old root")
    _assert_true(_check_heap(h), "invariant after heapreplace")
    _assert_eq(len(h), 5, "length unchanged after heapreplace")
    _end_group("heapreplace_basic")

def test_heapreplace_smaller():
    _start_group("heapreplace_smaller")
    h = [1, 5, 10, 15, 20]
    heapify(h)
    old = heapreplace(h, 0)
    _assert_eq(old, 1, "heapreplace returns old min")
    _assert_eq(h[0], 0, "new root is 0")
    _assert_true(_check_heap(h), "invariant after replace with smaller")
    _end_group("heapreplace_smaller")

def test_heapreplace_larger():
    _start_group("heapreplace_larger")
    h = [1, 2, 3]
    heapify(h)
    old = heapreplace(h, 100)
    _assert_eq(old, 1, "heapreplace returns 1")
    _assert_true(_check_heap(h), "invariant after replace with large")
    _assert_eq(h[0], 2, "new root is 2")
    _end_group("heapreplace_larger")

test_heapreplace_basic()
test_heapreplace_smaller()
test_heapreplace_larger()

# ---------------------------------------------------------------------------
# Test: heappushpop — one function per case (already split)
# ---------------------------------------------------------------------------

def test_heappushpop_larger():
    _start_group("heappushpop_larger")
    h = [1, 3, 5]
    heapify(h)
    v = heappushpop(h, 4)
    _assert_eq(v, 1, "pushpop larger than root returns root")
    _assert_true(_check_heap(h), "invariant after pushpop larger")
    _assert_eq(len(h), 3, "length unchanged")
    _end_group("heappushpop_larger")

def test_heappushpop_smaller():
    _start_group("heappushpop_smaller")
    h = [3, 5, 7]
    heapify(h)
    v = heappushpop(h, 1)
    _assert_eq(v, 1, "pushpop smaller returns item")
    _assert_list_eq(h, [3, 5, 7], "heap unchanged")
    _end_group("heappushpop_smaller")

def test_heappushpop_equal():
    _start_group("heappushpop_equal")
    h = [3, 5, 7]
    heapify(h)
    v = heappushpop(h, 3)
    _assert_eq(v, 3, "pushpop equal returns item")
    _assert_true(_check_heap(h), "invariant after pushpop equal")
    _end_group("heappushpop_equal")

def test_heappushpop_empty():
    _start_group("heappushpop_empty")
    h = []
    v = heappushpop(h, 5)
    _assert_eq(v, 5, "pushpop empty returns item")
    _assert_eq(len(h), 0, "heap still empty")
    _end_group("heappushpop_empty")

test_heappushpop_larger()
test_heappushpop_smaller()
test_heappushpop_equal()
test_heappushpop_empty()

# ---------------------------------------------------------------------------
# Test: heapsort — split into 6 to avoid list reassignment
# ---------------------------------------------------------------------------

def test_heapsort_basic():
    _start_group("heapsort_basic")
    data = [5, 3, 7, 1, 9, 2, 8, 4, 6, 0]
    h = []
    for x in data:
        heappush(h, x)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "heapsort basic")
    _end_group("heapsort_basic")

def test_heapsort_sorted_input():
    _start_group("heapsort_sorted_input")
    data = [1, 2, 3, 4, 5]
    h = []
    for x in data:
        heappush(h, x)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [1, 2, 3, 4, 5], "heapsort sorted input")
    _end_group("heapsort_sorted_input")

def test_heapsort_reverse_input():
    _start_group("heapsort_reverse_input")
    data = [5, 4, 3, 2, 1]
    h = []
    for x in data:
        heappush(h, x)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [1, 2, 3, 4, 5], "heapsort reverse input")
    _end_group("heapsort_reverse_input")

def test_heapsort_duplicates():
    _start_group("heapsort_duplicates")
    data = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]
    h = []
    for x in data:
        heappush(h, x)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [1, 1, 2, 3, 3, 4, 5, 5, 5, 6, 9], "heapsort duplicates")
    _end_group("heapsort_duplicates")

def test_heapsort_single():
    _start_group("heapsort_single")
    h = []
    heappush(h, 42)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [42], "heapsort single")
    _end_group("heapsort_single")

def test_heapsort_large():
    _start_group("heapsort_large")
    h = []
    v = 17
    for i in range(500):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        heappush(h, v % 10000)
    result = []
    while h:
        result.append(heappop(h))
    ok = True
    for i in range(len(result) - 1):
        if result[i] > result[i + 1]:
            ok = False
    _assert_true(ok, "heapsort 500 sorted")
    _assert_eq(len(result), 500, "heapsort 500 length")
    _end_group("heapsort_large")

test_heapsort_basic()
test_heapsort_sorted_input()
test_heapsort_reverse_input()
test_heapsort_duplicates()
test_heapsort_single()
test_heapsort_large()

# ---------------------------------------------------------------------------
# Test: heapify then pop all — split into 2
# ---------------------------------------------------------------------------

def test_heapify_sort_basic():
    _start_group("heapify_sort_basic")
    data = [8, 3, 6, 1, 9, 4, 7, 2, 5, 0]
    h = []
    for x in data:
        h.append(x)
    heapify(h)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "heapify+pop sort")
    _end_group("heapify_sort_basic")

def test_heapify_sort_large():
    _start_group("heapify_sort_large")
    h = []
    v = 99
    for i in range(1000):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        h.append(v % 50000)
    heapify(h)
    result = []
    while h:
        result.append(heappop(h))
    ok = True
    for i in range(len(result) - 1):
        if result[i] > result[i + 1]:
            ok = False
    _assert_true(ok, "heapify+pop 1000 sorted")
    _assert_eq(len(result), 1000, "heapify+pop 1000 length")
    _end_group("heapify_sort_large")

test_heapify_sort_basic()
test_heapify_sort_large()

# ---------------------------------------------------------------------------
# Test: max-heap push — split from maxheap_basic
# ---------------------------------------------------------------------------

def test_maxheap_push():
    _start_group("maxheap_push")
    h = []
    heappush_max(h, 5)
    _assert_list_eq(h, [5], "maxheap push to empty")
    heappush_max(h, 3)
    _assert_eq(h[0], 5, "maxheap root stays largest")
    _assert_true(_check_maxheap(h), "maxheap invariant after 2 pushes")
    heappush_max(h, 7)
    _assert_eq(h[0], 7, "maxheap new root is largest")
    _assert_true(_check_maxheap(h), "maxheap invariant after 3 pushes")
    heappush_max(h, 10)
    _assert_eq(h[0], 10, "maxheap push 10 becomes root")
    _assert_true(_check_maxheap(h), "maxheap invariant after 4 pushes")
    _end_group("maxheap_push")

def test_maxheap_pop():
    _start_group("maxheap_pop")
    h = [10, 7, 5, 3]
    heapify_max(h)
    v = heappop_max(h)
    _assert_eq(v, 10, "maxheap pop returns largest")
    _assert_true(_check_maxheap(h), "maxheap invariant after pop")
    v = heappop_max(h)
    _assert_eq(v, 7, "maxheap pop returns next largest")
    v = heappop_max(h)
    _assert_eq(v, 5, "maxheap pop 3rd")
    v = heappop_max(h)
    _assert_eq(v, 3, "maxheap pop last")
    _assert_eq(len(h), 0, "maxheap empty")
    _end_group("maxheap_pop")

def test_maxheap_pop_single():
    _start_group("maxheap_pop_single")
    h = [42]
    v = heappop_max(h)
    _assert_eq(v, 42, "maxheap pop single")
    _end_group("maxheap_pop_single")

test_maxheap_push()
test_maxheap_pop()
test_maxheap_pop_single()

# ---------------------------------------------------------------------------
# Test: heapify_max — split into 6 to avoid list reassignment
# ---------------------------------------------------------------------------

def test_heapify_max_sorted():
    _start_group("heapify_max_sorted")
    h = [1, 2, 3, 4, 5]
    heapify_max(h)
    _assert_true(_check_maxheap(h), "heapify_max sorted")
    _assert_eq(h[0], 5, "heapify_max sorted root")
    _end_group("heapify_max_sorted")

def test_heapify_max_reverse():
    _start_group("heapify_max_reverse")
    h = [5, 4, 3, 2, 1]
    heapify_max(h)
    _assert_true(_check_maxheap(h), "heapify_max reverse")
    _assert_eq(h[0], 5, "heapify_max reverse root")
    _end_group("heapify_max_reverse")

def test_heapify_max_random():
    _start_group("heapify_max_random")
    h = [3, 1, 4, 1, 5, 9, 2, 6]
    heapify_max(h)
    _assert_true(_check_maxheap(h), "heapify_max random")
    _assert_eq(h[0], 9, "heapify_max random root")
    _end_group("heapify_max_random")

def test_heapify_max_empty():
    _start_group("heapify_max_empty")
    h = []
    heapify_max(h)
    _assert_true(_check_maxheap(h), "heapify_max empty")
    _end_group("heapify_max_empty")

def test_heapify_max_single():
    _start_group("heapify_max_single")
    h = [42]
    heapify_max(h)
    _assert_eq(h[0], 42, "heapify_max single")
    _end_group("heapify_max_single")

def test_heapify_max_large():
    _start_group("heapify_max_large")
    h = []
    v = 31
    for i in range(500):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        h.append(v % 5000)
    heapify_max(h)
    _assert_true(_check_maxheap(h), "heapify_max 500")
    _end_group("heapify_max_large")

test_heapify_max_sorted()
test_heapify_max_reverse()
test_heapify_max_random()
test_heapify_max_empty()
test_heapify_max_single()
test_heapify_max_large()

# ---------------------------------------------------------------------------
# Test: heapreplace_max — split into 2
# ---------------------------------------------------------------------------

def test_heapreplace_max_basic():
    _start_group("heapreplace_max_basic")
    h = [9, 5, 7, 3, 1]
    heapify_max(h)
    old = heapreplace_max(h, 4)
    _assert_eq(old, 9, "heapreplace_max returns old max")
    _assert_true(_check_maxheap(h), "maxheap invariant after replace")
    _assert_eq(len(h), 5, "length unchanged")
    _end_group("heapreplace_max_basic")

def test_heapreplace_max_larger():
    _start_group("heapreplace_max_larger")
    h = [5, 3, 1]
    heapify_max(h)
    old = heapreplace_max(h, 10)
    _assert_eq(old, 5, "heapreplace_max returns 5")
    _assert_eq(h[0], 10, "new root is 10")
    _assert_true(_check_maxheap(h), "maxheap invariant replace with larger")
    _end_group("heapreplace_max_larger")

test_heapreplace_max_basic()
test_heapreplace_max_larger()

# ---------------------------------------------------------------------------
# Test: heappushpop_max — split into 4
# ---------------------------------------------------------------------------

def test_heappushpop_max_smaller():
    _start_group("heappushpop_max_smaller")
    h = [9, 5, 7]
    heapify_max(h)
    v = heappushpop_max(h, 4)
    _assert_eq(v, 9, "maxheap pushpop smaller returns root")
    _assert_true(_check_maxheap(h), "maxheap invariant after pushpop")
    _assert_eq(len(h), 3, "length unchanged")
    _end_group("heappushpop_max_smaller")

def test_heappushpop_max_larger():
    _start_group("heappushpop_max_larger")
    h = [5, 3, 1]
    heapify_max(h)
    v = heappushpop_max(h, 10)
    _assert_eq(v, 10, "maxheap pushpop larger returns item")
    _assert_list_eq(h, [5, 3, 1], "maxheap unchanged")
    _end_group("heappushpop_max_larger")

def test_heappushpop_max_equal():
    _start_group("heappushpop_max_equal")
    h = [5, 3, 1]
    heapify_max(h)
    v = heappushpop_max(h, 5)
    _assert_eq(v, 5, "maxheap pushpop equal returns item")
    _end_group("heappushpop_max_equal")

def test_heappushpop_max_empty():
    _start_group("heappushpop_max_empty")
    h = []
    v = heappushpop_max(h, 5)
    _assert_eq(v, 5, "maxheap pushpop empty")
    _end_group("heappushpop_max_empty")

test_heappushpop_max_smaller()
test_heappushpop_max_larger()
test_heappushpop_max_equal()
test_heappushpop_max_empty()

# ---------------------------------------------------------------------------
# Test: max-heap sort — split into 3
# ---------------------------------------------------------------------------

def test_maxheap_sort_push():
    _start_group("maxheap_sort_push")
    data = [5, 3, 7, 1, 9, 2, 8, 4, 6, 0]
    h = []
    for x in data:
        heappush_max(h, x)
    result = []
    while h:
        result.append(heappop_max(h))
    _assert_list_eq(result, [9, 8, 7, 6, 5, 4, 3, 2, 1, 0], "maxheap sort desc")
    _end_group("maxheap_sort_push")

def test_maxheap_sort_heapify():
    _start_group("maxheap_sort_heapify")
    h = [8, 3, 6, 1, 9, 4, 7, 2, 5, 0]
    heapify_max(h)
    result = []
    while h:
        result.append(heappop_max(h))
    _assert_list_eq(result, [9, 8, 7, 6, 5, 4, 3, 2, 1, 0], "heapify_max+pop desc")
    _end_group("maxheap_sort_heapify")

def test_maxheap_sort_large():
    _start_group("maxheap_sort_large")
    h = []
    v = 53
    for i in range(500):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        h.append(v % 10000)
    heapify_max(h)
    result = []
    while h:
        result.append(heappop_max(h))
    ok = True
    for i in range(len(result) - 1):
        if result[i] < result[i + 1]:
            ok = False
    _assert_true(ok, "maxheap sort 500 desc")
    _assert_eq(len(result), 500, "maxheap sort 500 length")
    _end_group("maxheap_sort_large")

test_maxheap_sort_push()
test_maxheap_sort_heapify()
test_maxheap_sort_large()

# ---------------------------------------------------------------------------
# Test: precomputed push/pop sequences — split into 6
# ---------------------------------------------------------------------------

def test_precomputed_push09():
    _start_group("precomputed_push09")
    h = []
    for i in range(10):
        heappush(h, i)
    result = []
    for i in range(10):
        result.append(heappop(h))
    _assert_list_eq(result, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "push 0-9 pop all")
    _end_group("precomputed_push09")

def test_precomputed_push90():
    _start_group("precomputed_push90")
    h = []
    for i in range(10):
        heappush(h, 9 - i)
    result = []
    for i in range(10):
        result.append(heappop(h))
    _assert_list_eq(result, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "push 9-0 pop all")
    _end_group("precomputed_push90")

def test_precomputed_interleaved():
    _start_group("precomputed_interleaved")
    h = []
    heappush(h, 5)
    heappush(h, 3)
    v1 = heappop(h)
    _assert_eq(v1, 3, "interleave: pop 3")
    heappush(h, 7)
    heappush(h, 1)
    v2 = heappop(h)
    _assert_eq(v2, 1, "interleave: pop 1")
    v3 = heappop(h)
    _assert_eq(v3, 5, "interleave: pop 5")
    v4 = heappop(h)
    _assert_eq(v4, 7, "interleave: pop 7")
    _end_group("precomputed_interleaved")

def test_precomputed_replacements():
    _start_group("precomputed_replacements")
    h = [1, 2, 3, 4, 5]
    heapify(h)
    for i in range(10):
        heapreplace(h, i + 6)
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [11, 12, 13, 14, 15], "10 replacements")
    _end_group("precomputed_replacements")

def test_precomputed_pushpop_small():
    _start_group("precomputed_pushpop_small")
    h = [10, 20, 30]
    heapify(h)
    for i in range(5):
        v = heappushpop(h, i)
        _assert_eq(v, i, "pushpop small " + str(i))
    _assert_list_eq(h, [10, 20, 30], "heap unchanged after small pushpops")
    _end_group("precomputed_pushpop_small")

def test_precomputed_pushpop_replace():
    _start_group("precomputed_pushpop_replace")
    h = [1, 2, 3]
    heapify(h)
    results = [0]
    results.pop()
    for i in range(10, 15):
        v = heappushpop(h, i)
        results.append(v)
    _assert_list_eq(results, [1, 2, 3, 10, 11], "pushpop replace sequence")
    final = [0]
    final.pop()
    while h:
        final.append(heappop(h))
    _assert_list_eq(final, [12, 13, 14], "heap after replace sequence")
    _end_group("precomputed_pushpop_replace")

test_precomputed_push09()
test_precomputed_push90()
test_precomputed_interleaved()
test_precomputed_replacements()
test_precomputed_pushpop_small()
test_precomputed_pushpop_replace()

# ---------------------------------------------------------------------------
# Test: stress invariant — split into min and max
# ---------------------------------------------------------------------------

def test_stress_invariant_min():
    _start_group("stress_invariant_min")
    h = []
    v = 7
    ok = True
    for i in range(200):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        heappush(h, v % 1000)
        if (i + 1) % 20 == 0:
            if not _check_heap(h):
                ok = False
    _assert_true(ok, "invariant during 200 pushes")
    ok = True
    for i in range(100):
        heappop(h)
        if (i + 1) % 10 == 0:
            if not _check_heap(h):
                ok = False
    _assert_true(ok, "invariant during 100 pops")
    ok = True
    for i in range(50):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        heapreplace(h, v % 1000)
        if (i + 1) % 10 == 0:
            if not _check_heap(h):
                ok = False
    _assert_true(ok, "invariant during 50 replacements")
    ok = True
    for i in range(50):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        heappushpop(h, v % 1000)
        if (i + 1) % 10 == 0:
            if not _check_heap(h):
                ok = False
    _assert_true(ok, "invariant during 50 pushpops")
    _end_group("stress_invariant_min")

def test_stress_invariant_max():
    _start_group("stress_invariant_max")
    h = []
    v = 13
    ok = True
    for i in range(200):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        heappush_max(h, v % 1000)
        if (i + 1) % 20 == 0:
            if not _check_maxheap(h):
                ok = False
    _assert_true(ok, "maxheap invariant during 200 pushes")
    ok = True
    for i in range(100):
        heappop_max(h)
        if (i + 1) % 10 == 0:
            if not _check_maxheap(h):
                ok = False
    _assert_true(ok, "maxheap invariant during 100 pops")
    ok = True
    for i in range(50):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        heapreplace_max(h, v % 1000)
        if (i + 1) % 10 == 0:
            if not _check_maxheap(h):
                ok = False
    _assert_true(ok, "maxheap invariant during 50 replacements")
    ok = True
    for i in range(50):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        heappushpop_max(h, v % 1000)
        if (i + 1) % 10 == 0:
            if not _check_maxheap(h):
                ok = False
    _assert_true(ok, "maxheap invariant during 50 pushpops")
    _end_group("stress_invariant_max")

test_stress_invariant_min()
test_stress_invariant_max()

# ---------------------------------------------------------------------------
# Test: heapsort with various sizes — helper function avoids loop reassignment
# ---------------------------------------------------------------------------

def _heapsort_one_size(size):
    h = []
    v = size * 7 + 3
    expected_sum = 0
    for i in range(size):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        val = v % 10000
        heappush(h, val)
        expected_sum = expected_sum + val
    result = []
    actual_sum = 0
    while h:
        val = heappop(h)
        result.append(val)
        actual_sum = actual_sum + val
    ok = True
    for i in range(len(result) - 1):
        if result[i] > result[i + 1]:
            ok = False
    _assert_true(ok, "heapsort size " + str(size) + " sorted")
    _assert_eq(len(result), size, "heapsort size " + str(size) + " length")
    _assert_eq(actual_sum, expected_sum, "heapsort size " + str(size) + " sum")

def test_heapsort_sizes():
    _start_group("heapsort_sizes")
    for size in [1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65,
                  127, 128, 129, 255, 256, 257]:
        _heapsort_one_size(size)
    _end_group("heapsort_sizes")

test_heapsort_sizes()

# ---------------------------------------------------------------------------
# Test: maxheap sort sizes — helper function avoids loop reassignment
# ---------------------------------------------------------------------------

def _maxheap_sort_one_size(size):
    h = []
    v = size * 11 + 5
    expected_sum = 0
    for i in range(size):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        val = v % 10000
        h.append(val)
        expected_sum = expected_sum + val
    heapify_max(h)
    result = []
    actual_sum = 0
    while h:
        val = heappop_max(h)
        result.append(val)
        actual_sum = actual_sum + val
    ok = True
    for i in range(len(result) - 1):
        if result[i] < result[i + 1]:
            ok = False
    _assert_true(ok, "maxheap sort size " + str(size) + " desc")
    _assert_eq(len(result), size, "maxheap sort size " + str(size) + " length")
    _assert_eq(actual_sum, expected_sum, "maxheap sort size " + str(size) + " sum")

def test_maxheap_sort_sizes():
    _start_group("maxheap_sort_sizes")
    for size in [1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128]:
        _maxheap_sort_one_size(size)
    _end_group("maxheap_sort_sizes")

test_maxheap_sort_sizes()

# ---------------------------------------------------------------------------
# Test: priority queue — split into basic and median
# ---------------------------------------------------------------------------

def test_priority_queue_basic():
    _start_group("priority_queue_basic")
    pq = [0]
    pq.pop()
    heappush(pq, 5)
    heappush(pq, 1)
    heappush(pq, 3)
    heappush(pq, 7)
    heappush(pq, 2)
    order = [0]
    order.pop()
    while pq:
        order.append(heappop(pq))
    _assert_list_eq(order, [1, 2, 3, 5, 7], "priority queue order")
    _end_group("priority_queue_basic")

def test_priority_queue_median():
    _start_group("priority_queue_median")
    upper = [0]
    upper.pop()
    lower = [0]
    lower.pop()
    data = [5, 15, 1, 3, 8, 7, 9, 10, 6, 11, 4]
    for x in data:
        if not lower or x <= 0 - lower[0]:
            heappush_max(lower, x)
        else:
            heappush(upper, x)
        if len(lower) > len(upper) + 1:
            moved = heappop_max(lower)
            heappush(upper, moved)
        if len(upper) > len(lower):
            moved = heappop(upper)
            heappush_max(lower, moved)
    _assert_eq(lower[0], 7, "running median = 7")
    _assert_eq(len(lower), 6, "lower half size")
    _assert_eq(len(upper), 5, "upper half size")
    _end_group("priority_queue_median")

test_priority_queue_basic()
test_priority_queue_median()

# ---------------------------------------------------------------------------
# Test: edge cases — split into 7 functions
# ---------------------------------------------------------------------------

def test_edge_push_into_single():
    _start_group("edge_push_into_single")
    h = [5]
    heappush(h, 3)
    _assert_eq(h[0], 3, "push into single: root")
    _assert_eq(len(h), 2, "push into single: len")
    heappush(h, 7)
    _assert_eq(h[0], 3, "push into pair: root stays")
    _assert_true(_check_heap(h), "push into pair: invariant")
    _end_group("edge_push_into_single")

def test_edge_pop_to_empty():
    _start_group("edge_pop_to_empty")
    h = [1, 2]
    heapify(h)
    v = heappop(h)
    _assert_eq(v, 1, "pop to single: got 1")
    v = heappop(h)
    _assert_eq(v, 2, "pop last: got 2")
    _assert_eq(len(h), 0, "pop last: empty")
    _end_group("edge_pop_to_empty")

def test_edge_replace_single():
    _start_group("edge_replace_single")
    h = [5]
    old = heapreplace(h, 3)
    _assert_eq(old, 5, "replace single: old = 5")
    _assert_eq(h[0], 3, "replace single: new root = 3")
    _end_group("edge_replace_single")

def test_edge_negative():
    _start_group("edge_negative")
    h = [-5, -1, -3, -2, -4]
    heapify(h)
    _assert_eq(h[0], -5, "heapify neg: root = -5")
    _assert_true(_check_heap(h), "heapify neg: invariant")
    result = []
    while h:
        result.append(heappop(h))
    _assert_list_eq(result, [-5, -4, -3, -2, -1], "heapsort neg")
    _end_group("edge_negative")

def test_edge_zeros():
    _start_group("edge_zeros")
    h = [0, 0, 0, 0, 0]
    heapify(h)
    _assert_true(_check_heap(h), "heapify zeros: invariant")
    v = heappop(h)
    _assert_eq(v, 0, "pop from zeros")
    _end_group("edge_zeros")

def test_edge_large_values():
    _start_group("edge_large_values")
    h = [1000000, 999999, 999998]
    heapify(h)
    _assert_eq(h[0], 999998, "heapify large vals: root")
    _assert_true(_check_heap(h), "heapify large vals: invariant")
    _end_group("edge_large_values")

def test_edge_push_duplicate():
    _start_group("edge_push_duplicate")
    h = [1, 3, 5]
    heapify(h)
    heappush(h, 1)
    _assert_eq(h[0], 1, "push dup root: still 1")
    _assert_eq(len(h), 4, "push dup root: len 4")
    _assert_true(_check_heap(h), "push dup root: invariant")
    v1 = heappop(h)
    v2 = heappop(h)
    _assert_eq(v1, 1, "pop dup 1st")
    _assert_eq(v2, 1, "pop dup 2nd")
    _end_group("edge_push_duplicate")

test_edge_push_into_single()
test_edge_pop_to_empty()
test_edge_replace_single()
test_edge_negative()
test_edge_zeros()
test_edge_large_values()
test_edge_push_duplicate()

# ---------------------------------------------------------------------------
# Test: heapify idempotent — split into 2
# ---------------------------------------------------------------------------

def test_heapify_idempotent():
    _start_group("heapify_idempotent")
    data = [9, 7, 5, 3, 1, 2, 4, 6, 8, 0]
    h1 = [0]
    h1.pop()
    for x in data:
        h1.append(x)
    heapify(h1)
    before = [0]
    before.pop()
    for x in h1:
        before.append(x)
    heapify(h1)
    _assert_list_eq(h1, before, "heapify idempotent")
    _end_group("heapify_idempotent")

def test_heapify_idempotent_order():
    _start_group("heapify_idempotent_order")
    data = [9, 7, 5, 3, 1, 2, 4, 6, 8, 0]
    h_copy = [0]
    h_copy.pop()
    for x in data:
        h_copy.append(x)
    heapify(h_copy)
    result = []
    while h_copy:
        result.append(heappop(h_copy))
    _assert_list_eq(result, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "heapify pop order")
    _end_group("heapify_idempotent_order")

test_heapify_idempotent()
test_heapify_idempotent_order()

# ---------------------------------------------------------------------------
# Test: all equal elements — split into min and max
# ---------------------------------------------------------------------------

def test_all_equal_min():
    _start_group("all_equal_min")
    h = [7, 7, 7, 7, 7, 7, 7]
    heapify(h)
    _assert_true(_check_heap(h), "all equal invariant")
    _assert_eq(h[0], 7, "all equal root")
    heappush(h, 7)
    _assert_true(_check_heap(h), "push equal invariant")
    _assert_eq(len(h), 8, "push equal len")
    v = heappop(h)
    _assert_eq(v, 7, "pop equal")
    _assert_true(_check_heap(h), "after pop equal invariant")
    v = heapreplace(h, 7)
    _assert_eq(v, 7, "replace equal")
    _assert_true(_check_heap(h), "after replace equal invariant")
    v = heappushpop(h, 7)
    _assert_eq(v, 7, "pushpop equal")
    _end_group("all_equal_min")

def test_all_equal_max():
    _start_group("all_equal_max")
    h = [3, 3, 3, 3, 3]
    heapify_max(h)
    _assert_true(_check_maxheap(h), "maxheap all equal invariant")
    v = heappop_max(h)
    _assert_eq(v, 3, "maxheap pop equal")
    _end_group("all_equal_max")

test_all_equal_min()
test_all_equal_max()

# ---------------------------------------------------------------------------
# Test: min and max heaps on same data
# ---------------------------------------------------------------------------

def test_combined():
    _start_group("combined_ops")
    data = [15, 8, 23, 4, 42, 16, 1, 30, 7, 20]
    min_h = []
    for x in data:
        heappush(min_h, x)
    max_h = []
    for x in data:
        heappush_max(max_h, x)
    min_sorted = [0]
    min_sorted.pop()
    while min_h:
        min_sorted.append(heappop(min_h))
    max_sorted = [0]
    max_sorted.pop()
    while max_h:
        max_sorted.append(heappop_max(max_h))
    max_reversed = [0]
    max_reversed.pop()
    for i in range(len(max_sorted) - 1, -1, -1):
        max_reversed.append(max_sorted[i])
    _assert_list_eq(min_sorted, max_reversed, "min sort == reverse max sort")
    _end_group("combined_ops")

test_combined()

# ---------------------------------------------------------------------------
# Test: pushpop boundary conditions — split into 6
# ---------------------------------------------------------------------------

def test_pushpop_boundary_eq_root():
    _start_group("pushpop_boundary_eq")
    h = [1, 2, 3]
    heapify(h)
    v = heappushpop(h, 1)
    _assert_eq(v, 1, "pushpop boundary: item == root returns item")
    _assert_eq(h[0], 1, "pushpop boundary: root unchanged")
    _assert_true(_check_heap(h), "pushpop boundary: invariant")
    _end_group("pushpop_boundary_eq")

def test_pushpop_boundary_below():
    _start_group("pushpop_boundary_below")
    h = [5, 10, 15]
    heapify(h)
    v = heappushpop(h, 4)
    _assert_eq(v, 4, "pushpop below root returns item")
    _end_group("pushpop_boundary_below")

def test_pushpop_boundary_above():
    _start_group("pushpop_boundary_above")
    h = [5, 10, 15]
    heapify(h)
    v = heappushpop(h, 6)
    _assert_eq(v, 5, "pushpop above root returns old root")
    _assert_true(_check_heap(h), "pushpop above root invariant")
    _end_group("pushpop_boundary_above")

def test_pushpop_boundary_max_eq():
    _start_group("pushpop_boundary_max_eq")
    h = [10, 5, 3]
    heapify_max(h)
    v = heappushpop_max(h, 10)
    _assert_eq(v, 10, "maxheap pushpop boundary: item == root")
    _assert_eq(h[0], 10, "maxheap pushpop boundary: root unchanged")
    _end_group("pushpop_boundary_max_eq")

def test_pushpop_boundary_max_above():
    _start_group("pushpop_boundary_max_above")
    h = [10, 5, 3]
    heapify_max(h)
    v = heappushpop_max(h, 11)
    _assert_eq(v, 11, "maxheap pushpop above root")
    _end_group("pushpop_boundary_max_above")

def test_pushpop_boundary_max_below():
    _start_group("pushpop_boundary_max_below")
    h = [10, 5, 3]
    heapify_max(h)
    v = heappushpop_max(h, 7)
    _assert_eq(v, 10, "maxheap pushpop below root returns max")
    _assert_true(_check_maxheap(h), "maxheap pushpop below invariant")
    _end_group("pushpop_boundary_max_below")

test_pushpop_boundary_eq_root()
test_pushpop_boundary_below()
test_pushpop_boundary_above()
test_pushpop_boundary_max_eq()
test_pushpop_boundary_max_above()
test_pushpop_boundary_max_below()

# ---------------------------------------------------------------------------
# Test: large random data — split into min and max
# ---------------------------------------------------------------------------

def test_large_random_min():
    _start_group("large_random_min")
    h = []
    v = 2023
    for i in range(2000):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        heappush(h, v % 100000)
    _assert_true(_check_heap(h), "2000 pushes invariant")
    _assert_eq(len(h), 2000, "2000 pushes length")
    for i in range(1000):
        heappop(h)
    _assert_true(_check_heap(h), "after 1000 pops invariant")
    _assert_eq(len(h), 1000, "after 1000 pops length")
    for i in range(500):
        v = (v * 1103515245 + 12345) % (2 ** 31)
        heappushpop(h, v % 100000)
    _assert_true(_check_heap(h), "after 500 pushpops invariant")
    _assert_eq(len(h), 1000, "after 500 pushpops length")
    result = []
    while h:
        result.append(heappop(h))
    ok = True
    for i in range(len(result) - 1):
        if result[i] > result[i + 1]:
            ok = False
    _assert_true(ok, "final 1000 sorted")
    _assert_eq(len(result), 1000, "final 1000 length")
    _end_group("large_random_min")

def test_large_random_max():
    _start_group("large_random_max")
    h = []
    v = 2024
    for i in range(2000):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        heappush_max(h, v % 100000)
    _assert_true(_check_maxheap(h), "maxheap 2000 pushes invariant")
    for i in range(1000):
        heappop_max(h)
    _assert_true(_check_maxheap(h), "maxheap after 1000 pops invariant")
    for i in range(500):
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        heappushpop_max(h, v % 100000)
    _assert_true(_check_maxheap(h), "maxheap after 500 pushpops invariant")
    result = []
    while h:
        result.append(heappop_max(h))
    ok = True
    for i in range(len(result) - 1):
        if result[i] < result[i + 1]:
            ok = False
    _assert_true(ok, "maxheap final 1000 desc sorted")
    _assert_eq(len(result), 1000, "maxheap final 1000 length")
    _end_group("large_random_max")

test_large_random_min()
test_large_random_max()

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("")
_total = _pass_count + _fail_count
if _fail_count == 0:
    print("ALL TESTS PASSED: " + str(_total) + "/" + str(_total))
else:
    print("TESTS FAILED: " + str(_fail_count) + " of " + str(_total))
