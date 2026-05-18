# Auto-adapted from CPython Lib/test/test_bisect.py
# Tests fastpy's ability to compile and run the bisect module
# Stdlib source inlined from: C:\Users\inhah\AppData\Local\Python\pythoncore-3.13-64\Lib\bisect.py

# ======================================================================
# Inlined stdlib module: bisect
# ======================================================================

"""Bisection algorithms."""


def insort_right(a, x, lo=0, hi=None, *, key=None):
    """Insert item x in list a, and keep it sorted assuming a is sorted.

    If x is already in a, insert it to the right of the rightmost x.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """
    if key is None:
        lo = bisect_right(a, x, lo, hi)
    else:
        lo = bisect_right(a, key(x), lo, hi, key=key)
    a.insert(lo, x)


def bisect_right(a, x, lo=0, hi=None, *, key=None):
    """Return the index where to insert item x in list a, assuming a is sorted.

    The return value i is such that all e in a[:i] have e <= x, and all e in
    a[i:] have e > x.  So if x already appears in the list, a.insert(i, x) will
    insert just after the rightmost x already there.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """

    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = len(a)
    # Note, the comparison uses "<" to match the
    # __lt__() logic in list.sort() and in heapq.
    if key is None:
        while lo < hi:
            mid = (lo + hi) // 2
            if x < a[mid]:
                hi = mid
            else:
                lo = mid + 1
    else:
        while lo < hi:
            mid = (lo + hi) // 2
            if x < key(a[mid]):
                hi = mid
            else:
                lo = mid + 1
    return lo


def insort_left(a, x, lo=0, hi=None, *, key=None):
    """Insert item x in list a, and keep it sorted assuming a is sorted.

    If x is already in a, insert it to the left of the leftmost x.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """

    if key is None:
        lo = bisect_left(a, x, lo, hi)
    else:
        lo = bisect_left(a, key(x), lo, hi, key=key)
    a.insert(lo, x)

def bisect_left(a, x, lo=0, hi=None, *, key=None):
    """Return the index where to insert item x in list a, assuming a is sorted.

    The return value i is such that all e in a[:i] have e < x, and all e in
    a[i:] have e >= x.  So if x already appears in the list, a.insert(i, x) will
    insert just before the leftmost x already there.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """

    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = len(a)
    # Note, the comparison uses "<" to match the
    # __lt__() logic in list.sort() and in heapq.
    if key is None:
        while lo < hi:
            mid = (lo + hi) // 2
            if a[mid] < x:
                lo = mid + 1
            else:
                hi = mid
    else:
        while lo < hi:
            mid = (lo + hi) // 2
            if key(a[mid]) < x:
                lo = mid + 1
            else:
                hi = mid
    return lo


# Overwrite above definitions with a fast C implementation
# [stripped C-extension import from line 111]
# Create aliases
bisect = bisect_right
insort = insort_right

# ======================================================================
# Assertion helpers
# ======================================================================

# Assertion helpers (replacing unittest.TestCase methods)
def assertEqual(a, b, msg=None):
    if a != b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b))

def assertNotEqual(a, b, msg=None):
    if a == b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b))

def assertAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) > 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b) + " within " + str(places) + " places")

def assertNotAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) <= 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b) + " within " + str(places) + " places")

def assertTrue(x, msg=None):
    if not x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected True, got " + str(x))

def assertFalse(x, msg=None):
    if x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected False, got " + str(x))

def assertIs(a, b, msg=None):
    if a is not b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not " + str(b))

def assertIsNot(a, b, msg=None):
    if a is b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is " + str(b))

def assertIsNone(x, msg=None):
    if x is not None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(x) + " is not None")

def assertIsNotNone(x, msg=None):
    if x is None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("unexpected None")

def assertIn(a, b, msg=None):
    if a not in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not in " + str(b))

def assertNotIn(a, b, msg=None):
    if a in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " in " + str(b))

def assertIsInstance(a, b, msg=None):
    if not isinstance(a, b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not instance of " + str(b))

def assertGreater(a, b, msg=None):
    if not (a > b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not greater than " + str(b))

def assertGreaterEqual(a, b, msg=None):
    if not (a >= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not >= " + str(b))

def assertLess(a, b, msg=None):
    if not (a < b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not less than " + str(b))

def assertLessEqual(a, b, msg=None):
    if not (a <= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not <= " + str(b))

def assertSequenceEqual(a, b, msg=None):
    if len(a) != len(b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError("sequences differ in length: " + str(len(a)) + " vs " + str(len(b)))
    for i in range(len(a)):
        if a[i] != b[i]:
            if msg:
                raise AssertionError(msg)
            raise AssertionError("sequences differ at index " + str(i) + ": " + str(a[i]) + " != " + str(b[i]))

def assertListEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)

def assertTupleEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)


# ======================================================================
# Helper functions from test file
# ======================================================================

class Range(object):
    """A trivial range()-like object that has an insert() method."""

    def __init__(self, start, stop):
        self.start = start
        self.stop = stop
        self.last_insert = None

    def __len__(self):
        return self.stop - self.start

    def __getitem__(self, idx):
        n = self.stop - self.start
        if idx < 0:
            idx += n
        if idx >= n:
            raise IndexError(idx)
        return self.start + idx

    def insert(self, idx, item):
        self.last_insert = (idx, item)

class LenOnly:
    """Dummy sequence class defining __len__ but not __getitem__."""

    def __len__(self):
        return 10

class GetOnly:
    """Dummy sequence class defining __getitem__ but not __len__."""

    def __getitem__(self, ndx):
        return 10

class CmpErr:
    """Dummy element that always raises an error during comparison"""

    def __lt__(self, other):
        raise ZeroDivisionError
    __gt__ = __lt__
    __le__ = __lt__
    __ge__ = __lt__
    __eq__ = __lt__
    __ne__ = __lt__


# ======================================================================
# Test functions (extracted from CPython test suite)
# ======================================================================

# Test functions from TestBisectPython
def TestBisectPython__test_random(n=25):
    precomputedCases = [(bisect_right, [], 1, 0), (bisect_right, [1], 0, 0), (bisect_right, [1], 1, 1), (bisect_right, [1], 2, 1), (bisect_right, [1, 1], 0, 0), (bisect_right, [1, 1], 1, 2), (bisect_right, [1, 1], 2, 2), (bisect_right, [1, 1, 1], 0, 0), (bisect_right, [1, 1, 1], 1, 3), (bisect_right, [1, 1, 1], 2, 3), (bisect_right, [1, 1, 1, 1], 0, 0), (bisect_right, [1, 1, 1, 1], 1, 4), (bisect_right, [1, 1, 1, 1], 2, 4), (bisect_right, [1, 2], 0, 0), (bisect_right, [1, 2], 1, 1), (bisect_right, [1, 2], 1.5, 1), (bisect_right, [1, 2], 2, 2), (bisect_right, [1, 2], 3, 2), (bisect_right, [1, 1, 2, 2], 0, 0), (bisect_right, [1, 1, 2, 2], 1, 2), (bisect_right, [1, 1, 2, 2], 1.5, 2), (bisect_right, [1, 1, 2, 2], 2, 4), (bisect_right, [1, 1, 2, 2], 3, 4), (bisect_right, [1, 2, 3], 0, 0), (bisect_right, [1, 2, 3], 1, 1), (bisect_right, [1, 2, 3], 1.5, 1), (bisect_right, [1, 2, 3], 2, 2), (bisect_right, [1, 2, 3], 2.5, 2), (bisect_right, [1, 2, 3], 3, 3), (bisect_right, [1, 2, 3], 4, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 10), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10), (bisect_left, [], 1, 0), (bisect_left, [1], 0, 0), (bisect_left, [1], 1, 0), (bisect_left, [1], 2, 1), (bisect_left, [1, 1], 0, 0), (bisect_left, [1, 1], 1, 0), (bisect_left, [1, 1], 2, 2), (bisect_left, [1, 1, 1], 0, 0), (bisect_left, [1, 1, 1], 1, 0), (bisect_left, [1, 1, 1], 2, 3), (bisect_left, [1, 1, 1, 1], 0, 0), (bisect_left, [1, 1, 1, 1], 1, 0), (bisect_left, [1, 1, 1, 1], 2, 4), (bisect_left, [1, 2], 0, 0), (bisect_left, [1, 2], 1, 0), (bisect_left, [1, 2], 1.5, 1), (bisect_left, [1, 2], 2, 1), (bisect_left, [1, 2], 3, 2), (bisect_left, [1, 1, 2, 2], 0, 0), (bisect_left, [1, 1, 2, 2], 1, 0), (bisect_left, [1, 1, 2, 2], 1.5, 2), (bisect_left, [1, 1, 2, 2], 2, 2), (bisect_left, [1, 1, 2, 2], 3, 4), (bisect_left, [1, 2, 3], 0, 0), (bisect_left, [1, 2, 3], 1, 0), (bisect_left, [1, 2, 3], 1.5, 1), (bisect_left, [1, 2, 3], 2, 1), (bisect_left, [1, 2, 3], 2.5, 2), (bisect_left, [1, 2, 3], 3, 2), (bisect_left, [1, 2, 3], 4, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10)]
    from random import randrange
    for i in range(n):
        data = [randrange(0, n, 2) for j in range(i)]
        data.sort()
        elem = randrange(-1, n + 1)
        ip = bisect_left(data, elem)
        if ip < len(data):
            assertTrue(elem <= data[ip])
        if ip > 0:
            assertTrue(data[ip - 1] < elem)
        ip = bisect_right(data, elem)
        if ip < len(data):
            assertTrue(elem < data[ip])
        if ip > 0:
            assertTrue(data[ip - 1] <= elem)

def TestBisectPython__test_optionalSlicing():
    precomputedCases = [(bisect_right, [], 1, 0), (bisect_right, [1], 0, 0), (bisect_right, [1], 1, 1), (bisect_right, [1], 2, 1), (bisect_right, [1, 1], 0, 0), (bisect_right, [1, 1], 1, 2), (bisect_right, [1, 1], 2, 2), (bisect_right, [1, 1, 1], 0, 0), (bisect_right, [1, 1, 1], 1, 3), (bisect_right, [1, 1, 1], 2, 3), (bisect_right, [1, 1, 1, 1], 0, 0), (bisect_right, [1, 1, 1, 1], 1, 4), (bisect_right, [1, 1, 1, 1], 2, 4), (bisect_right, [1, 2], 0, 0), (bisect_right, [1, 2], 1, 1), (bisect_right, [1, 2], 1.5, 1), (bisect_right, [1, 2], 2, 2), (bisect_right, [1, 2], 3, 2), (bisect_right, [1, 1, 2, 2], 0, 0), (bisect_right, [1, 1, 2, 2], 1, 2), (bisect_right, [1, 1, 2, 2], 1.5, 2), (bisect_right, [1, 1, 2, 2], 2, 4), (bisect_right, [1, 1, 2, 2], 3, 4), (bisect_right, [1, 2, 3], 0, 0), (bisect_right, [1, 2, 3], 1, 1), (bisect_right, [1, 2, 3], 1.5, 1), (bisect_right, [1, 2, 3], 2, 2), (bisect_right, [1, 2, 3], 2.5, 2), (bisect_right, [1, 2, 3], 3, 3), (bisect_right, [1, 2, 3], 4, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 10), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10), (bisect_left, [], 1, 0), (bisect_left, [1], 0, 0), (bisect_left, [1], 1, 0), (bisect_left, [1], 2, 1), (bisect_left, [1, 1], 0, 0), (bisect_left, [1, 1], 1, 0), (bisect_left, [1, 1], 2, 2), (bisect_left, [1, 1, 1], 0, 0), (bisect_left, [1, 1, 1], 1, 0), (bisect_left, [1, 1, 1], 2, 3), (bisect_left, [1, 1, 1, 1], 0, 0), (bisect_left, [1, 1, 1, 1], 1, 0), (bisect_left, [1, 1, 1, 1], 2, 4), (bisect_left, [1, 2], 0, 0), (bisect_left, [1, 2], 1, 0), (bisect_left, [1, 2], 1.5, 1), (bisect_left, [1, 2], 2, 1), (bisect_left, [1, 2], 3, 2), (bisect_left, [1, 1, 2, 2], 0, 0), (bisect_left, [1, 1, 2, 2], 1, 0), (bisect_left, [1, 1, 2, 2], 1.5, 2), (bisect_left, [1, 1, 2, 2], 2, 2), (bisect_left, [1, 1, 2, 2], 3, 4), (bisect_left, [1, 2, 3], 0, 0), (bisect_left, [1, 2, 3], 1, 0), (bisect_left, [1, 2, 3], 1.5, 1), (bisect_left, [1, 2, 3], 2, 1), (bisect_left, [1, 2, 3], 2.5, 2), (bisect_left, [1, 2, 3], 3, 2), (bisect_left, [1, 2, 3], 4, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10)]
    for func, data, elem, expected in precomputedCases:
        for lo in range(4):
            lo = min(len(data), lo)
            for hi in range(3, 8):
                hi = min(len(data), hi)
                ip = func(data, elem, lo, hi)
                assertTrue(lo <= ip <= hi)
                if func is bisect_left and ip < hi:
                    assertTrue(elem <= data[ip])
                if func is bisect_left and ip > lo:
                    assertTrue(data[ip - 1] < elem)
                if func is bisect_right and ip < hi:
                    assertTrue(elem < data[ip])
                if func is bisect_right and ip > lo:
                    assertTrue(data[ip - 1] <= elem)
                assertEqual(ip, max(lo, min(hi, expected)))

def TestBisectPython__test_backcompatibility():
    precomputedCases = [(bisect_right, [], 1, 0), (bisect_right, [1], 0, 0), (bisect_right, [1], 1, 1), (bisect_right, [1], 2, 1), (bisect_right, [1, 1], 0, 0), (bisect_right, [1, 1], 1, 2), (bisect_right, [1, 1], 2, 2), (bisect_right, [1, 1, 1], 0, 0), (bisect_right, [1, 1, 1], 1, 3), (bisect_right, [1, 1, 1], 2, 3), (bisect_right, [1, 1, 1, 1], 0, 0), (bisect_right, [1, 1, 1, 1], 1, 4), (bisect_right, [1, 1, 1, 1], 2, 4), (bisect_right, [1, 2], 0, 0), (bisect_right, [1, 2], 1, 1), (bisect_right, [1, 2], 1.5, 1), (bisect_right, [1, 2], 2, 2), (bisect_right, [1, 2], 3, 2), (bisect_right, [1, 1, 2, 2], 0, 0), (bisect_right, [1, 1, 2, 2], 1, 2), (bisect_right, [1, 1, 2, 2], 1.5, 2), (bisect_right, [1, 1, 2, 2], 2, 4), (bisect_right, [1, 1, 2, 2], 3, 4), (bisect_right, [1, 2, 3], 0, 0), (bisect_right, [1, 2, 3], 1, 1), (bisect_right, [1, 2, 3], 1.5, 1), (bisect_right, [1, 2, 3], 2, 2), (bisect_right, [1, 2, 3], 2.5, 2), (bisect_right, [1, 2, 3], 3, 3), (bisect_right, [1, 2, 3], 4, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 10), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10), (bisect_left, [], 1, 0), (bisect_left, [1], 0, 0), (bisect_left, [1], 1, 0), (bisect_left, [1], 2, 1), (bisect_left, [1, 1], 0, 0), (bisect_left, [1, 1], 1, 0), (bisect_left, [1, 1], 2, 2), (bisect_left, [1, 1, 1], 0, 0), (bisect_left, [1, 1, 1], 1, 0), (bisect_left, [1, 1, 1], 2, 3), (bisect_left, [1, 1, 1, 1], 0, 0), (bisect_left, [1, 1, 1, 1], 1, 0), (bisect_left, [1, 1, 1, 1], 2, 4), (bisect_left, [1, 2], 0, 0), (bisect_left, [1, 2], 1, 0), (bisect_left, [1, 2], 1.5, 1), (bisect_left, [1, 2], 2, 1), (bisect_left, [1, 2], 3, 2), (bisect_left, [1, 1, 2, 2], 0, 0), (bisect_left, [1, 1, 2, 2], 1, 0), (bisect_left, [1, 1, 2, 2], 1.5, 2), (bisect_left, [1, 1, 2, 2], 2, 2), (bisect_left, [1, 1, 2, 2], 3, 4), (bisect_left, [1, 2, 3], 0, 0), (bisect_left, [1, 2, 3], 1, 0), (bisect_left, [1, 2, 3], 1.5, 1), (bisect_left, [1, 2, 3], 2, 1), (bisect_left, [1, 2, 3], 2.5, 2), (bisect_left, [1, 2, 3], 3, 2), (bisect_left, [1, 2, 3], 4, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10)]
    assertEqual(bisect, bisect_right)

def TestBisectPython__test_lookups_with_key_function():
    precomputedCases = [(bisect_right, [], 1, 0), (bisect_right, [1], 0, 0), (bisect_right, [1], 1, 1), (bisect_right, [1], 2, 1), (bisect_right, [1, 1], 0, 0), (bisect_right, [1, 1], 1, 2), (bisect_right, [1, 1], 2, 2), (bisect_right, [1, 1, 1], 0, 0), (bisect_right, [1, 1, 1], 1, 3), (bisect_right, [1, 1, 1], 2, 3), (bisect_right, [1, 1, 1, 1], 0, 0), (bisect_right, [1, 1, 1, 1], 1, 4), (bisect_right, [1, 1, 1, 1], 2, 4), (bisect_right, [1, 2], 0, 0), (bisect_right, [1, 2], 1, 1), (bisect_right, [1, 2], 1.5, 1), (bisect_right, [1, 2], 2, 2), (bisect_right, [1, 2], 3, 2), (bisect_right, [1, 1, 2, 2], 0, 0), (bisect_right, [1, 1, 2, 2], 1, 2), (bisect_right, [1, 1, 2, 2], 1.5, 2), (bisect_right, [1, 1, 2, 2], 2, 4), (bisect_right, [1, 1, 2, 2], 3, 4), (bisect_right, [1, 2, 3], 0, 0), (bisect_right, [1, 2, 3], 1, 1), (bisect_right, [1, 2, 3], 1.5, 1), (bisect_right, [1, 2, 3], 2, 2), (bisect_right, [1, 2, 3], 2.5, 2), (bisect_right, [1, 2, 3], 3, 3), (bisect_right, [1, 2, 3], 4, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 10), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10), (bisect_left, [], 1, 0), (bisect_left, [1], 0, 0), (bisect_left, [1], 1, 0), (bisect_left, [1], 2, 1), (bisect_left, [1, 1], 0, 0), (bisect_left, [1, 1], 1, 0), (bisect_left, [1, 1], 2, 2), (bisect_left, [1, 1, 1], 0, 0), (bisect_left, [1, 1, 1], 1, 0), (bisect_left, [1, 1, 1], 2, 3), (bisect_left, [1, 1, 1, 1], 0, 0), (bisect_left, [1, 1, 1, 1], 1, 0), (bisect_left, [1, 1, 1, 1], 2, 4), (bisect_left, [1, 2], 0, 0), (bisect_left, [1, 2], 1, 0), (bisect_left, [1, 2], 1.5, 1), (bisect_left, [1, 2], 2, 1), (bisect_left, [1, 2], 3, 2), (bisect_left, [1, 1, 2, 2], 0, 0), (bisect_left, [1, 1, 2, 2], 1, 0), (bisect_left, [1, 1, 2, 2], 1.5, 2), (bisect_left, [1, 1, 2, 2], 2, 2), (bisect_left, [1, 1, 2, 2], 3, 4), (bisect_left, [1, 2, 3], 0, 0), (bisect_left, [1, 2, 3], 1, 0), (bisect_left, [1, 2, 3], 1.5, 1), (bisect_left, [1, 2, 3], 2, 1), (bisect_left, [1, 2, 3], 2.5, 2), (bisect_left, [1, 2, 3], 3, 2), (bisect_left, [1, 2, 3], 4, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10)]
    keyfunc = abs
    arr = sorted([2, -4, 6, 8, -10], key=keyfunc)
    precomputed_arr = list(map(keyfunc, arr))
    for x in precomputed_arr:
        assertEqual(bisect_left(arr, x, key=keyfunc), bisect_left(precomputed_arr, x))
        assertEqual(bisect_right(arr, x, key=keyfunc), bisect_right(precomputed_arr, x))
    keyfunc = str.casefold
    arr = sorted('aBcDeEfgHhiIiij', key=keyfunc)
    precomputed_arr = list(map(keyfunc, arr))
    for x in precomputed_arr:
        assertEqual(bisect_left(arr, x, key=keyfunc), bisect_left(precomputed_arr, x))
        assertEqual(bisect_right(arr, x, key=keyfunc), bisect_right(precomputed_arr, x))

def TestBisectPython__test_insort():
    precomputedCases = [(bisect_right, [], 1, 0), (bisect_right, [1], 0, 0), (bisect_right, [1], 1, 1), (bisect_right, [1], 2, 1), (bisect_right, [1, 1], 0, 0), (bisect_right, [1, 1], 1, 2), (bisect_right, [1, 1], 2, 2), (bisect_right, [1, 1, 1], 0, 0), (bisect_right, [1, 1, 1], 1, 3), (bisect_right, [1, 1, 1], 2, 3), (bisect_right, [1, 1, 1, 1], 0, 0), (bisect_right, [1, 1, 1, 1], 1, 4), (bisect_right, [1, 1, 1, 1], 2, 4), (bisect_right, [1, 2], 0, 0), (bisect_right, [1, 2], 1, 1), (bisect_right, [1, 2], 1.5, 1), (bisect_right, [1, 2], 2, 2), (bisect_right, [1, 2], 3, 2), (bisect_right, [1, 1, 2, 2], 0, 0), (bisect_right, [1, 1, 2, 2], 1, 2), (bisect_right, [1, 1, 2, 2], 1.5, 2), (bisect_right, [1, 1, 2, 2], 2, 4), (bisect_right, [1, 1, 2, 2], 3, 4), (bisect_right, [1, 2, 3], 0, 0), (bisect_right, [1, 2, 3], 1, 1), (bisect_right, [1, 2, 3], 1.5, 1), (bisect_right, [1, 2, 3], 2, 2), (bisect_right, [1, 2, 3], 2.5, 2), (bisect_right, [1, 2, 3], 3, 3), (bisect_right, [1, 2, 3], 4, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 10), (bisect_right, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10), (bisect_left, [], 1, 0), (bisect_left, [1], 0, 0), (bisect_left, [1], 1, 0), (bisect_left, [1], 2, 1), (bisect_left, [1, 1], 0, 0), (bisect_left, [1, 1], 1, 0), (bisect_left, [1, 1], 2, 2), (bisect_left, [1, 1, 1], 0, 0), (bisect_left, [1, 1, 1], 1, 0), (bisect_left, [1, 1, 1], 2, 3), (bisect_left, [1, 1, 1, 1], 0, 0), (bisect_left, [1, 1, 1, 1], 1, 0), (bisect_left, [1, 1, 1, 1], 2, 4), (bisect_left, [1, 2], 0, 0), (bisect_left, [1, 2], 1, 0), (bisect_left, [1, 2], 1.5, 1), (bisect_left, [1, 2], 2, 1), (bisect_left, [1, 2], 3, 2), (bisect_left, [1, 1, 2, 2], 0, 0), (bisect_left, [1, 1, 2, 2], 1, 0), (bisect_left, [1, 1, 2, 2], 1.5, 2), (bisect_left, [1, 1, 2, 2], 2, 2), (bisect_left, [1, 1, 2, 2], 3, 4), (bisect_left, [1, 2, 3], 0, 0), (bisect_left, [1, 2, 3], 1, 0), (bisect_left, [1, 2, 3], 1.5, 1), (bisect_left, [1, 2, 3], 2, 1), (bisect_left, [1, 2, 3], 2.5, 2), (bisect_left, [1, 2, 3], 3, 2), (bisect_left, [1, 2, 3], 4, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 0, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1, 0), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 1.5, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2, 1), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 2.5, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3, 3), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 4, 6), (bisect_left, [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 5, 10)]
    from random import shuffle
    keyfunc = abs
    data = list(range(-10, 11)) + list(range(-20, 20, 2))
    shuffle(data)
    target = []
    for x in data:
        insort_left(target, x, key=keyfunc)
        assertEqual(sorted(target, key=keyfunc), target)
    target = []
    for x in data:
        insort_right(target, x, key=keyfunc)
        assertEqual(sorted(target, key=keyfunc), target)


# Test functions from TestInsortPython
def TestInsortPython__test_backcompatibility():
    assertEqual(insort, insort_right)


# Test functions from TestDocExamplePython
def TestDocExamplePython__test_grades():

    def grade(score):
        i = bisect([60, 70, 80, 90], score)
        return 'FDCBA'[i]
    result = [grade(score) for score in [33, 99, 77, 70, 89, 90, 100]]
    assertEqual(result, ['F', 'A', 'C', 'C', 'B', 'A', 'A'])

def TestDocExamplePython__test_colors():
    data = [('red', 5), ('blue', 1), ('yellow', 8), ('black', 0)]
    data.sort(key=lambda r: r[1])
    keys = [r[1] for r in data]
    assertEqual(data[bisect_left(keys, 0)], ('black', 0))
    assertEqual(data[bisect_left(keys, 1)], ('blue', 1))
    assertEqual(data[bisect_left(keys, 5)], ('red', 5))
    assertEqual(data[bisect_left(keys, 8)], ('yellow', 8))


# Test functions from TestDocExampleC
def TestDocExampleC__test_grades():

    def grade(score):
        i = bisect([60, 70, 80, 90], score)
        return 'FDCBA'[i]
    result = [grade(score) for score in [33, 99, 77, 70, 89, 90, 100]]
    assertEqual(result, ['F', 'A', 'C', 'C', 'B', 'A', 'A'])

def TestDocExampleC__test_colors():
    data = [('red', 5), ('blue', 1), ('yellow', 8), ('black', 0)]
    data.sort(key=lambda r: r[1])
    keys = [r[1] for r in data]
    assertEqual(data[bisect_left(keys, 0)], ('black', 0))
    assertEqual(data[bisect_left(keys, 1)], ('blue', 1))
    assertEqual(data[bisect_left(keys, 5)], ('red', 5))
    assertEqual(data[bisect_left(keys, 8)], ('yellow', 8))


# ======================================================================
# Direct invocation
# ======================================================================

try:
    TestBisectPython__test_random()
    print("TestBisectPython.test_random: PASS")
except Exception as _e:
    print("TestBisectPython.test_random: FAIL -", _e)
try:
    TestBisectPython__test_optionalSlicing()
    print("TestBisectPython.test_optionalSlicing: PASS")
except Exception as _e:
    print("TestBisectPython.test_optionalSlicing: FAIL -", _e)
try:
    TestBisectPython__test_backcompatibility()
    print("TestBisectPython.test_backcompatibility: PASS")
except Exception as _e:
    print("TestBisectPython.test_backcompatibility: FAIL -", _e)
try:
    TestBisectPython__test_lookups_with_key_function()
    print("TestBisectPython.test_lookups_with_key_function: PASS")
except Exception as _e:
    print("TestBisectPython.test_lookups_with_key_function: FAIL -", _e)
try:
    TestBisectPython__test_insort()
    print("TestBisectPython.test_insort: PASS")
except Exception as _e:
    print("TestBisectPython.test_insort: FAIL -", _e)
try:
    TestInsortPython__test_backcompatibility()
    print("TestInsortPython.test_backcompatibility: PASS")
except Exception as _e:
    print("TestInsortPython.test_backcompatibility: FAIL -", _e)
try:
    TestDocExamplePython__test_grades()
    print("TestDocExamplePython.test_grades: PASS")
except Exception as _e:
    print("TestDocExamplePython.test_grades: FAIL -", _e)
try:
    TestDocExamplePython__test_colors()
    print("TestDocExamplePython.test_colors: PASS")
except Exception as _e:
    print("TestDocExamplePython.test_colors: FAIL -", _e)
try:
    TestDocExampleC__test_grades()
    print("TestDocExampleC.test_grades: PASS")
except Exception as _e:
    print("TestDocExampleC.test_grades: FAIL -", _e)
try:
    TestDocExampleC__test_colors()
    print("TestDocExampleC.test_colors: PASS")
except Exception as _e:
    print("TestDocExampleC.test_colors: FAIL -", _e)