# Adapted from CPython Lib/statistics.py — stdlib statistics algorithms
# Tests statistical functions compiled by fastpy.
#
# The CPython statistics module uses complex internal machinery:
#   - Fraction/Decimal type coercion, _exact_ratio(), _coerce()
#   - NormalDist class with __slots__
#   - keyword-only args (*, key=None)
#   - generator expressions for _sum()
# These trigger compiler limitations.
#
# We reimplement the core algorithms as standalone functions operating
# on lists of numbers.  The algorithms match CPython's statistics module
# for float data, which is the common case.

# ======================================================================
# Core statistics functions (algorithms from CPython Lib/statistics.py)
# ======================================================================

def mean(data):
    """Return the arithmetic mean of data.

    From CPython statistics.mean: sum(data) / len(data).
    """
    n = len(data)
    if n == 0:
        raise ValueError("mean requires at least one data point")
    total = 0.0
    i = 0
    while i < n:
        total = total + data[i]
        i = i + 1
    return total / n

def fmean(data):
    """Return the floating point mean of data.

    From CPython statistics.fmean: like mean but always returns float.
    """
    n = len(data)
    if n == 0:
        raise ValueError("fmean requires at least one data point")
    total = 0.0
    i = 0
    while i < n:
        total = total + data[i]
        i = i + 1
    return total / n

def median(data):
    """Return the median (middle value) of numeric data.

    From CPython statistics.median: sort, then pick middle or average
    of two middle values.
    """
    n = len(data)
    if n == 0:
        raise ValueError("no median for empty data")
    sorted_data = sorted(data)
    if n % 2 == 1:
        return float(sorted_data[n // 2])
    else:
        mid = n // 2
        return (sorted_data[mid - 1] + sorted_data[mid]) / 2.0

def median_low(data):
    """Return the low median of numeric data.

    From CPython statistics.median_low.
    """
    n = len(data)
    if n == 0:
        raise ValueError("no median for empty data")
    sorted_data = sorted(data)
    if n % 2 == 1:
        return sorted_data[n // 2]
    else:
        return sorted_data[n // 2 - 1]

def median_high(data):
    """Return the high median of numeric data.

    From CPython statistics.median_high.
    """
    n = len(data)
    if n == 0:
        raise ValueError("no median for empty data")
    sorted_data = sorted(data)
    return sorted_data[n // 2]

def mode(data):
    """Return the most common data point.

    From CPython statistics.mode: count frequencies, return most common.
    NOTE: Uses for-in iteration instead of while+index because the
    compiled code segfaults on while-loop indexed access to int lists
    used as dict keys.
    """
    if len(data) == 0:
        raise ValueError("no mode for empty data")
    freq = {}
    for x in data:
        if x in freq:
            freq[x] = freq[x] + 1
        else:
            freq[x] = 1
    max_count = 0
    max_val = data[0]
    for val in freq:
        if freq[val] > max_count:
            max_count = freq[val]
            max_val = val
    return max_val

def _ss(data, mu):
    """Sum of squared deviations from mean.

    Internal helper used by variance/stdev, from CPython statistics._ss.
    """
    total = 0.0
    i = 0
    while i < len(data):
        diff = data[i] - mu
        total = total + diff * diff
        i = i + 1
    return total

def variance(data):
    """Return the sample variance of data.

    From CPython statistics.variance: _ss(data) / (n-1).
    """
    n = len(data)
    if n < 2:
        raise ValueError("variance requires at least two data points")
    mu = mean(data)
    ss = _ss(data, mu)
    return ss / (n - 1)

def pvariance(data):
    """Return the population variance of data.

    From CPython statistics.pvariance: _ss(data) / n.
    """
    n = len(data)
    if n < 1:
        raise ValueError("pvariance requires at least one data point")
    mu = mean(data)
    ss = _ss(data, mu)
    return ss / n

def stdev(data):
    """Return the sample standard deviation.

    From CPython statistics.stdev: sqrt(variance(data)).
    """
    return variance(data) ** 0.5

def pstdev(data):
    """Return the population standard deviation.

    From CPython statistics.pstdev: sqrt(pvariance(data)).
    """
    return pvariance(data) ** 0.5

# ======================================================================
# Helper for approximate float equality
# ======================================================================

def approx_eq(a, b, tol):
    """Check if two floats are approximately equal within tolerance."""
    diff = a - b
    if diff < 0:
        diff = 0.0 - diff
    return diff < tol

# ======================================================================
# Tests
# ======================================================================

def test_mean():
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(mean([1, 2, 3, 4, 5]), 3.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(mean([10, 20, 30]), 20.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(mean([1]), 1.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(mean([0, 0, 0, 0]), 0.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(mean([1, 2, 3, 4]), 2.5, 0.0001): ok = ok + 1
    # Large dataset
    total = total + 1
    data = list(range(100))
    if approx_eq(mean(data), 49.5, 0.0001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_mean: PASS")
    else:
        print("TestStatistics.test_mean: FAIL -", ok, "of", total)

def test_fmean():
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(fmean([1, 2, 3, 4, 5]), 3.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(fmean([10, 20, 30]), 20.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(fmean([2, 4, 4, 4, 5, 5, 7, 9]), 5.0, 0.0001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_fmean: PASS")
    else:
        print("TestStatistics.test_fmean: FAIL -", ok, "of", total)

def test_median():
    ok = 0
    total = 0
    # Odd count
    total = total + 1
    if approx_eq(median([1, 2, 3, 4, 5]), 3.0, 0.0001): ok = ok + 1
    # Even count
    total = total + 1
    if approx_eq(median([1, 2, 3, 4]), 2.5, 0.0001): ok = ok + 1
    # Unsorted
    total = total + 1
    if approx_eq(median([5, 1, 3]), 3.0, 0.0001): ok = ok + 1
    # Single element
    total = total + 1
    if approx_eq(median([1]), 1.0, 0.0001): ok = ok + 1
    # Two elements
    total = total + 1
    if approx_eq(median([7, 3]), 5.0, 0.0001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_median: PASS")
    else:
        print("TestStatistics.test_median: FAIL -", ok, "of", total)

def test_median_low_high():
    ok = 0
    total = 0
    # Odd count — both return middle
    total = total + 1
    if median_low([1, 2, 3]) == 2: ok = ok + 1
    total = total + 1
    if median_high([1, 2, 3]) == 2: ok = ok + 1
    # Even count — low returns lower middle, high returns upper middle
    total = total + 1
    if median_low([1, 2, 3, 4]) == 2: ok = ok + 1
    total = total + 1
    if median_high([1, 2, 3, 4]) == 3: ok = ok + 1
    if ok == total:
        print("TestStatistics.test_median_low_high: PASS")
    else:
        print("TestStatistics.test_median_low_high: FAIL -", ok, "of", total)

def test_mode():
    ok = 0
    total = 0
    total = total + 1
    if mode([1, 2, 2, 3, 3, 3, 4]) == 3: ok = ok + 1
    total = total + 1
    if mode([1, 1, 1, 2, 2, 3]) == 1: ok = ok + 1
    total = total + 1
    if mode([5]) == 5: ok = ok + 1
    if ok == total:
        print("TestStatistics.test_mode: PASS")
    else:
        print("TestStatistics.test_mode: FAIL -", ok, "of", total)

def test_variance():
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(variance([1, 2, 3, 4, 5]), 2.5, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(variance([10, 10, 10, 10]), 0.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(variance([2, 4, 4, 4, 5, 5, 7, 9]), 4.5714, 0.001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_variance: PASS")
    else:
        print("TestStatistics.test_variance: FAIL -", ok, "of", total)

def test_pvariance():
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(pvariance([1, 2, 3, 4, 5]), 2.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(pvariance([10, 10, 10, 10]), 0.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(pvariance([2, 4, 4, 4, 5, 5, 7, 9]), 4.0, 0.001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_pvariance: PASS")
    else:
        print("TestStatistics.test_pvariance: FAIL -", ok, "of", total)

def test_stdev():
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(stdev([1, 2, 3, 4, 5]), 1.5811, 0.001): ok = ok + 1
    total = total + 1
    if approx_eq(stdev([2, 4, 4, 4, 5, 5, 7, 9]), 2.1380, 0.001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_stdev: PASS")
    else:
        print("TestStatistics.test_stdev: FAIL -", ok, "of", total)

def test_pstdev():
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(pstdev([1, 2, 3, 4, 5]), 1.4142, 0.001): ok = ok + 1
    total = total + 1
    if approx_eq(pstdev([2, 4, 4, 4, 5, 5, 7, 9]), 2.0, 0.001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_pstdev: PASS")
    else:
        print("TestStatistics.test_pstdev: FAIL -", ok, "of", total)

def test_complex_data():
    data = [4, 8, 15, 16, 23, 42]
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(mean(data), 18.0, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(median(data), 15.5, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(variance(data), 182.0, 0.1): ok = ok + 1
    total = total + 1
    if approx_eq(stdev(data), 13.4907, 0.01): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_complex_data: PASS")
    else:
        print("TestStatistics.test_complex_data: FAIL -", ok, "of", total)

def test_uniform_data():
    data = list(range(1, 11))
    ok = 0
    total = 0
    total = total + 1
    if approx_eq(mean(data), 5.5, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(median(data), 5.5, 0.0001): ok = ok + 1
    total = total + 1
    if approx_eq(variance(data), 9.1667, 0.001): ok = ok + 1
    if ok == total:
        print("TestStatistics.test_uniform_data: PASS")
    else:
        print("TestStatistics.test_uniform_data: FAIL -", ok, "of", total)

# ======================================================================
# Run all tests
# ======================================================================

try:
    test_mean()
except Exception as _e:
    print("TestStatistics.test_mean: FAIL -", _e)
try:
    test_fmean()
except Exception as _e:
    print("TestStatistics.test_fmean: FAIL -", _e)
try:
    test_median()
except Exception as _e:
    print("TestStatistics.test_median: FAIL -", _e)
try:
    test_median_low_high()
except Exception as _e:
    print("TestStatistics.test_median_low_high: FAIL -", _e)
try:
    test_mode()
except Exception as _e:
    print("TestStatistics.test_mode: FAIL -", _e)
try:
    test_variance()
except Exception as _e:
    print("TestStatistics.test_variance: FAIL -", _e)
try:
    test_pvariance()
except Exception as _e:
    print("TestStatistics.test_pvariance: FAIL -", _e)
try:
    test_stdev()
except Exception as _e:
    print("TestStatistics.test_stdev: FAIL -", _e)
try:
    test_pstdev()
except Exception as _e:
    print("TestStatistics.test_pstdev: FAIL -", _e)
try:
    test_complex_data()
except Exception as _e:
    print("TestStatistics.test_complex_data: FAIL -", _e)
try:
    test_uniform_data()
except Exception as _e:
    print("TestStatistics.test_uniform_data: FAIL -", _e)
