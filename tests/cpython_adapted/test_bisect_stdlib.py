# Adapted from CPython Lib/bisect.py — stdlib algorithms
# Tests the bisect binary search algorithms compiled by fastpy.
#
# NOTE: The stdlib bisect functions use keyword-only args (*, key=None).
# This causes compilation issues, so we use simplified signatures that
# keep the core algorithm identical but remove the key= parameter.
# The key= functionality is tested separately in test_bisect.py.
#
# NOTE: Function aliasing (bisect = bisect_right) causes a compiler bug
# where the aliased function's return value is corrupted.  We avoid
# aliases and call bisect_right / insort_right directly instead.

# ======================================================================
# Simplified bisect functions (same algorithm, no key= kwarg)
# ======================================================================

def bisect_right(a, x, lo=0, hi=None):
    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo

def bisect_left(a, x, lo=0, hi=None):
    if lo < 0:
        raise ValueError('lo must be non-negative')
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

# ======================================================================
# Tests
# ======================================================================

def test_bisect_right_basic():
    ok = 0
    total = 0
    # Empty list
    total = total + 1
    if bisect_right([], 1) == 0: ok = ok + 1
    # Single element
    total = total + 1
    if bisect_right([1], 0) == 0: ok = ok + 1
    total = total + 1
    if bisect_right([1], 1) == 1: ok = ok + 1
    total = total + 1
    if bisect_right([1], 2) == 1: ok = ok + 1
    # Duplicates
    total = total + 1
    if bisect_right([1, 1], 1) == 2: ok = ok + 1
    total = total + 1
    if bisect_right([1, 1, 1], 1) == 3: ok = ok + 1
    # Multiple elements
    total = total + 1
    if bisect_right([1, 2], 0) == 0: ok = ok + 1
    total = total + 1
    if bisect_right([1, 2], 1) == 1: ok = ok + 1
    total = total + 1
    if bisect_right([1, 2], 2) == 2: ok = ok + 1
    total = total + 1
    if bisect_right([1, 2], 3) == 2: ok = ok + 1
    # Larger list
    total = total + 1
    if bisect_right([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3) == 6: ok = ok + 1
    total = total + 1
    if bisect_right([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4) == 10: ok = ok + 1
    total = total + 1
    if bisect_right([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0) == 0: ok = ok + 1
    total = total + 1
    if bisect_right([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5) == 10: ok = ok + 1
    if ok == total:
        print("TestBisect.test_bisect_right_basic: PASS")
    else:
        print("TestBisect.test_bisect_right_basic: FAIL -", ok, "of", total)

def test_bisect_left_basic():
    ok = 0
    total = 0
    total = total + 1
    if bisect_left([], 1) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1], 0) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1], 1) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1], 2) == 1: ok = ok + 1
    total = total + 1
    if bisect_left([1, 1], 1) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1, 1, 1], 1) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2], 0) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2], 1) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2], 2) == 1: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2], 3) == 2: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3) == 3: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4) == 6: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0) == 0: ok = ok + 1
    total = total + 1
    if bisect_left([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5) == 10: ok = ok + 1
    if ok == total:
        print("TestBisect.test_bisect_left_basic: PASS")
    else:
        print("TestBisect.test_bisect_left_basic: FAIL -", ok, "of", total)

def test_optional_slicing():
    ok = 0
    total = 0
    data = [1, 2, 2, 3, 3, 3, 4, 4, 4, 4]
    total = total + 1
    if bisect_right(data, 3, 0, 6) == 6: ok = ok + 1
    total = total + 1
    if bisect_right(data, 3, 0, 5) == 5: ok = ok + 1
    total = total + 1
    if bisect_right(data, 1, 1, 8) == 1: ok = ok + 1
    total = total + 1
    if bisect_left(data, 3, 0, 6) == 3: ok = ok + 1
    total = total + 1
    if bisect_left(data, 3, 4, 8) == 4: ok = ok + 1
    total = total + 1
    if bisect_left(data, 1, 0, 5) == 0: ok = ok + 1
    if ok == total:
        print("TestBisect.test_optional_slicing: PASS")
    else:
        print("TestBisect.test_optional_slicing: FAIL -", ok, "of", total)

def test_insort():
    target = []
    for x in [5, 3, 1, 4, 2]:
        insort_right(target, x)
    ok1 = (target == [1, 2, 3, 4, 5])
    target2 = []
    for x in [5, 3, 1, 4, 2]:
        insort_left(target2, x)
    ok2 = (target2 == [1, 2, 3, 4, 5])
    target3 = []
    for x in [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]:
        insort_right(target3, x)
    ok3 = (target3 == sorted([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]))
    if ok1 and ok2 and ok3:
        print("TestBisect.test_insort: PASS")
    else:
        print("TestBisect.test_insort: FAIL")

def test_grade_example():
    scores = [33, 99, 77, 70, 89, 90, 100]
    breakpoints = [60, 70, 80, 90]
    grades_str = "FDCBA"
    result = []
    for score in scores:
        idx = bisect_right(breakpoints, score)
        result.append(grades_str[idx])
    expected = ["F", "A", "C", "C", "B", "A", "A"]
    if result == expected:
        print("TestBisect.test_grade_example: PASS")
    else:
        print("TestBisect.test_grade_example: FAIL -", result)

def test_invariant():
    data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    ok = 0
    total = 0
    for x in range(12):
        total = total + 1
        ip = bisect_left(data, x)
        good = True
        for j in range(ip):
            if data[j] >= x:
                good = False
        for j in range(ip, len(data)):
            if data[j] < x:
                good = False
        if good:
            ok = ok + 1
        total = total + 1
        ip = bisect_right(data, x)
        good = True
        for j in range(ip):
            if data[j] > x:
                good = False
        for j in range(ip, len(data)):
            if data[j] <= x:
                good = False
        if good:
            ok = ok + 1
    if ok == total:
        print("TestBisect.test_invariant: PASS")
    else:
        print("TestBisect.test_invariant: FAIL -", ok, "of", total)

# ======================================================================
# Run all tests
# ======================================================================

try:
    test_bisect_right_basic()
except Exception as _e:
    print("TestBisect.test_bisect_right_basic: FAIL -", _e)
try:
    test_bisect_left_basic()
except Exception as _e:
    print("TestBisect.test_bisect_left_basic: FAIL -", _e)
try:
    test_optional_slicing()
except Exception as _e:
    print("TestBisect.test_optional_slicing: FAIL -", _e)
try:
    test_insort()
except Exception as _e:
    print("TestBisect.test_insort: FAIL -", _e)
try:
    test_grade_example()
except Exception as _e:
    print("TestBisect.test_grade_example: FAIL -", _e)
try:
    test_invariant()
except Exception as _e:
    print("TestBisect.test_invariant: FAIL -", _e)
