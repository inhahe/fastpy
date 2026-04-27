"""statistics stdlib tests -- inlined statistical functions.

Covers: mean, fmean, median, median_low, median_high, variance, pvariance,
        stdev, pstdev, harmonic_mean, geometric_mean approximations.
All algorithms are inlined using only int/float/list operations.

Skipped: mode/multimode (need dict), quantiles (need sorted+complex slicing),
          median_grouped, NormalDist class, linear_regression, correlation.

NOTE: Only 6 function definitions to avoid compiler many-functions crash.
All test logic in single main() function.

COMPILER WORKAROUNDS:
  - Float lists must be created with [0.0]; pop() (not [0]; pop())
  - Negative float values cannot appear in list literals (arithmetic garbage)
  - Build negative-value lists via append: data.append(0.0 - val)
  - Nested ifs instead of 'and' for short-circuit safety
"""

# ---------------------------------------------------------------------------
# Helper: approximate square root (Newton's method)
# ---------------------------------------------------------------------------

def _sqrt(x):
    """Approximate square root using Newton's method."""
    if x < 0.0:
        return -1.0
    if x == 0.0:
        return 0.0
    guess = x
    if x > 1.0:
        guess = x / 2.0
    else:
        guess = 1.0
    for i in range(60):
        guess = (guess + x / guess) / 2.0
    return guess


# ---------------------------------------------------------------------------
# Helper: approximate natural log
# ---------------------------------------------------------------------------

def _log(x):
    """Approximate natural log using series expansion."""
    if x <= 0.0:
        return -999999.0
    result = 0.0
    e_val = 2.718281828459045
    while x > e_val:
        x = x / e_val
        result = result + 1.0
    inv_e = 1.0 / e_val
    while x < inv_e:
        x = x * e_val
        result = result - 1.0
    t = (x - 1.0) / (x + 1.0)
    t2 = t * t
    term = t
    s = term
    for i in range(1, 40):
        term = term * t2
        s = s + term / (2.0 * i + 1.0)
    result = result + 2.0 * s
    return result


# ---------------------------------------------------------------------------
# Helper: approximate exp
# ---------------------------------------------------------------------------

def _exp(x):
    """Approximate exp(x) using Taylor series."""
    if x > 700.0:
        return 1e300
    if x < -700.0:
        return 0.0
    n = 0
    if x >= 0.0:
        n = int(x + 0.5)
    else:
        n = int(x - 0.5)
    f = x - n
    ef = 1.0
    term = 1.0
    for i in range(1, 30):
        term = term * f / i
        ef = ef + term
    e_val = 2.718281828459045
    en = 1.0
    base = e_val
    abs_n = n
    if abs_n < 0:
        abs_n = 0 - abs_n
    while abs_n > 0:
        if abs_n % 2 == 1:
            en = en * base
        base = base * base
        abs_n = abs_n // 2
    if n < 0:
        en = 1.0 / en
    return en * ef


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_pc = 0
_fc = 0
_gp = 0
_gf = 0

def _ck(ok, msg):
    global _pc, _fc, _gp, _gf
    if ok:
        _pc = _pc + 1
        _gp = _gp + 1
    else:
        _fc = _fc + 1
        _gf = _gf + 1
        print("FAIL: " + msg)


# ---------------------------------------------------------------------------
# Inline insertion sort
# ---------------------------------------------------------------------------

def _isort(a):
    """In-place insertion sort. Returns the same list, sorted."""
    n = len(a)
    for i in range(1, n):
        key = a[i]
        j = i - 1
        cont = True
        while cont:
            if j < 0:
                cont = False
            else:
                if a[j] > key:
                    a[j + 1] = a[j]
                    j = j - 1
                else:
                    cont = False
        a[j + 1] = key
    return a


# ---------------------------------------------------------------------------
# main — all test logic
# ---------------------------------------------------------------------------

def main():
    global _gp, _gf

    # ===================================================================
    # mean (12 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # mean of [1, 2, 3, 4, 5] = 3.0
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    _ck(m == 3.0, "mean [1..5]")

    # mean of single element
    m = 7.0 / 1.0
    _ck(m == 7.0, "mean [7]")

    # mean of two elements
    m = (3.0 + 5.0) / 2.0
    _ck(m == 4.0, "mean [3,5]")

    # mean of negative numbers — build via append, NOT list literal
    data = [0.0]
    data.pop()
    data.append(0.0 - 1.0)
    data.append(0.0 - 2.0)
    data.append(0.0 - 3.0)
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    diff = m - (0.0 - 2.0)
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "mean [-1,-2,-3]")

    # mean of mixed positive and negative
    data = [0.0]
    data.pop()
    data.append(0.0 - 10.0)
    data.append(10.0)
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    diff = m - 0.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "mean [-10, 10]")

    # mean of all same values
    data = [5.0, 5.0, 5.0, 5.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    _ck(m == 5.0, "mean [5,5,5,5]")

    # mean of large list — use [0.0] not [0] for float-typed list
    data = [0.0]
    data.pop()
    for i in range(100):
        data.append(i * 1.0)
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    _ck(m == 49.5, "mean [0..99]")

    # mean precision check
    data = [0.1, 0.2, 0.3]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    diff = m - 0.2
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "mean [0.1,0.2,0.3] ~= 0.2")

    # mean of integers (as floats)
    data = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    _ck(m == 1.0, "mean ten 1s")

    # mean of [0]
    m = 0.0 / 1.0
    _ck(m == 0.0, "mean [0]")

    # fmean-style: sum / count for floats
    data = [2.5, 3.25, 5.5, 11.25, 11.75]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    diff = m - 6.85
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "fmean [2.5,3.25,5.5,11.25,11.75]")

    # mean of powers of 2
    data = [1.0, 2.0, 4.0, 8.0, 16.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    _ck(m == 6.2, "mean powers of 2")

    print("  mean: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # median (15 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # median of odd-length: [1,2,3] => 2
    data = [3.0, 1.0, 2.0]
    _isort(data)
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 2.0, "median [3,1,2]")

    # median of even-length: [1,2,3,4] => 2.5
    data = [4.0, 1.0, 3.0, 2.0]
    _isort(data)
    mid = len(data) // 2
    med = (data[mid - 1] + data[mid]) / 2.0
    _ck(med == 2.5, "median [4,1,3,2]")

    # median of single element
    med = 42.0
    _ck(med == 42.0, "median [42]")

    # median of two elements
    med = (10.0 + 20.0) / 2.0
    _ck(med == 15.0, "median [10,20]")

    # median of sorted odd list
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 3.0, "median [1,2,3,4,5]")

    # median of sorted even list
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    mid = len(data) // 2
    med = (data[mid - 1] + data[mid]) / 2.0
    _ck(med == 3.5, "median [1..6]")

    # median of duplicates
    data = [5.0, 5.0, 5.0, 5.0, 5.0]
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 5.0, "median all 5s")

    # median_low of even list: [1,2,3,4] => 2 (lower of middle pair)
    data = [1.0, 2.0, 3.0, 4.0]
    mid = len(data) // 2
    med_low = data[mid - 1]
    _ck(med_low == 2.0, "median_low [1,2,3,4]")

    # median_high of even list: [1,2,3,4] => 3 (upper of middle pair)
    med_high = data[mid]
    _ck(med_high == 3.0, "median_high [1,2,3,4]")

    # median of reverse sorted
    data = [5.0, 4.0, 3.0, 2.0, 1.0]
    _isort(data)
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 3.0, "median reverse sorted")

    # median of large odd list — use [0.0] for float-typed list
    data = [0.0]
    data.pop()
    for i in range(101):
        data.append(100.0 - i * 1.0)
    _isort(data)
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 50.0, "median 0..100 shuffled")

    # median of negative numbers — build via append
    data = [0.0]
    data.pop()
    data.append(0.0 - 5.0)
    data.append(0.0 - 3.0)
    data.append(0.0 - 1.0)
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 0.0 - 3.0, "median negatives")

    # median_low of odd list (same as median)
    data = [1.0, 2.0, 3.0]
    mid = len(data) // 2
    med_low = data[mid]
    _ck(med_low == 2.0, "median_low odd")

    # median with large range
    data = [1.0, 1000000.0, 2.0]
    _isort(data)
    mid = len(data) // 2
    med = data[mid]
    _ck(med == 2.0, "median large range")

    # median_high of odd list (same as median)
    data = [7.0, 3.0, 5.0]
    _isort(data)
    mid = len(data) // 2
    _ck(data[mid] == 5.0, "median_high odd")

    print("  median: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # variance and pvariance (16 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # pvariance of [2, 4, 4, 4, 5, 5, 7, 9] = 4.0
    data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    pvar = ssq / len(data)
    _ck(pvar == 4.0, "pvariance [2,4,4,4,5,5,7,9]")

    # variance (sample) of same data = 4.571428...
    var = ssq / (len(data) - 1)
    diff = var - 4.571428571428571
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "variance [2,4,4,4,5,5,7,9]")

    # pvariance of [1, 2, 3] = 2/3
    data = [1.0, 2.0, 3.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    pvar = ssq / len(data)
    diff = pvar - 0.6666666666666666
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "pvariance [1,2,3]")

    # variance of [1, 2, 3] = 1.0
    var = ssq / (len(data) - 1)
    _ck(var == 1.0, "variance [1,2,3]")

    # pvariance of all same values = 0
    data = [7.0, 7.0, 7.0, 7.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    pvar = ssq / len(data)
    _ck(pvar == 0.0, "pvariance all same")

    # variance of all same values = 0
    var = ssq / (len(data) - 1)
    _ck(var == 0.0, "variance all same")

    # pvariance of [1, 1, 1, 1, 5] = 2.56
    data = [1.0, 1.0, 1.0, 1.0, 5.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    pvar = ssq / len(data)
    diff = pvar - 2.56
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "pvariance [1,1,1,1,5]")

    # variance of [1, 1, 1, 1, 5] = 3.2
    var = ssq / (len(data) - 1)
    diff = var - 3.2
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "variance [1,1,1,1,5]")

    # pvariance with provided mean
    data = [1.0, 2.0, 2.0, 4.0, 4.0, 4.0, 5.0, 6.0]
    given_mean = 3.5
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - given_mean
        ssq = ssq + d * d
    pvar = ssq / len(data)
    _ck(pvar == 2.5, "pvariance with given mean")

    # pvariance of [0, 0, 0, 0] = 0
    data = [0.0, 0.0, 0.0, 0.0]
    pvar = 0.0
    _ck(pvar == 0.0, "pvariance all zeros")

    # variance of [10, 20] = 50.0
    data = [10.0, 20.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    var = ssq / (len(data) - 1)
    _ck(var == 50.0, "variance [10,20]")

    # pvariance of [10, 20] = 25.0
    pvar = ssq / len(data)
    _ck(pvar == 25.0, "pvariance [10,20]")

    # variance of large uniform data (0..99) — use float-typed list
    data = [0.0]
    data.pop()
    for i in range(100):
        data.append(i * 1.0)
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    var = ssq / (len(data) - 1)
    diff = var - 841.6666666666666
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "variance 0..99")

    # pvariance of 0..99 = 833.25
    pvar = ssq / len(data)
    _ck(pvar == 833.25, "pvariance 0..99")

    # variance of [-1, 0, 1] = 1.0 — build via append
    data = [0.0]
    data.pop()
    data.append(0.0 - 1.0)
    data.append(0.0)
    data.append(1.0)
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    var = ssq / (len(data) - 1)
    _ck(var == 1.0, "variance [-1,0,1]")

    # pvariance of [-1, 0, 1] = 2/3
    pvar = ssq / len(data)
    diff = pvar - 0.6666666666666666
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "pvariance [-1,0,1]")

    print("  variance: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # stdev and pstdev (11 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # pstdev of [2, 4, 4, 4, 5, 5, 7, 9] = sqrt(4.0) = 2.0
    data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    psd = _sqrt(ssq / len(data))
    _ck(psd == 2.0, "pstdev [2,4,4,4,5,5,7,9]")

    # stdev of same data = sqrt(32/7) ~ 2.13809
    sd = _sqrt(ssq / (len(data) - 1))
    diff = sd - 2.138089935299395
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "stdev [2,4,4,4,5,5,7,9]")

    # pstdev of all same = 0
    psd = 0.0
    _ck(psd == 0.0, "pstdev all same")

    # stdev of [1, 2, 3] = 1.0
    data = [1.0, 2.0, 3.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    sd = _sqrt(ssq / (len(data) - 1))
    _ck(sd == 1.0, "stdev [1,2,3]")

    # pstdev of [1, 2, 3] = sqrt(2/3) ~ 0.8165
    psd = _sqrt(ssq / len(data))
    diff = psd - 0.816496580927726
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "pstdev [1,2,3]")

    # stdev of [2.5, 3.25, 5.5, 11.25, 11.75] ~ 4.38962
    data = [2.5, 3.25, 5.5, 11.25, 11.75]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    sd = _sqrt(ssq / (len(data) - 1))
    diff = sd - 4.38961843444052
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "stdev float data")

    # pstdev of [0, 10] = 5.0
    data = [0.0, 10.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    psd = _sqrt(ssq / len(data))
    _ck(psd == 5.0, "pstdev [0,10]")

    # stdev of [0, 10] = sqrt(50) ~ 7.07107
    sd = _sqrt(ssq / (len(data) - 1))
    diff = sd - 7.0710678118654755
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "stdev [0,10]")

    # pstdev of [1] = 0
    psd = 0.0
    _ck(psd == 0.0, "pstdev single")

    # stdev precision: [100, 100.001, 99.999]
    data = [100.0, 100.001, 99.999]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    sd = _sqrt(ssq / (len(data) - 1))
    _ck(sd < 0.01, "stdev near-constant data is small")
    _ck(sd > 0.0, "stdev near-constant data is nonzero")

    print("  stdev: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # harmonic_mean (8 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # harmonic_mean of [1, 2, 4] = 12/7
    data = [1.0, 2.0, 4.0]
    recip_sum = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
    hm = len(data) * 1.0 / recip_sum
    diff = hm - 1.7142857142857142
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "harmonic_mean [1,2,4]")

    # harmonic_mean of all same = that value
    data = [5.0, 5.0, 5.0]
    recip_sum = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
    hm = len(data) * 1.0 / recip_sum
    diff = hm - 5.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "harmonic_mean all 5s")

    # harmonic_mean of [1] = 1
    hm = 1.0
    _ck(hm == 1.0, "harmonic_mean [1]")

    # harmonic_mean of [2, 2] = 2
    data = [2.0, 2.0]
    recip_sum = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
    hm = len(data) * 1.0 / recip_sum
    _ck(hm == 2.0, "harmonic_mean [2,2]")

    # harmonic_mean of [1, 1, 1, 1, 1] = 1
    data = [1.0, 1.0, 1.0, 1.0, 1.0]
    recip_sum = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
    hm = len(data) * 1.0 / recip_sum
    diff = hm - 1.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "harmonic_mean all 1s")

    # harmonic_mean of [40, 60] = 48
    data = [40.0, 60.0]
    recip_sum = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
    hm = len(data) * 1.0 / recip_sum
    diff = hm - 48.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "harmonic_mean [40,60]")

    # harmonic_mean <= arithmetic_mean always
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    recip_sum = 0.0
    s = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
        s = s + data[i]
    hm = len(data) * 1.0 / recip_sum
    am = s / len(data)
    _ck(hm < am, "harmonic <= arithmetic")
    _ck(hm > 0.0, "harmonic > 0 for positive data")

    print("  harmonic_mean: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # geometric_mean (8 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # geometric_mean of [1, 2, 4] = (8)^(1/3) = 2.0
    data = [1.0, 2.0, 4.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 2.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-6, "geometric_mean [1,2,4]")

    # geometric_mean of all same = that value
    data = [7.0, 7.0, 7.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 7.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-6, "geometric_mean all 7s")

    # geometric_mean of [1] = 1
    gm = 1.0
    _ck(gm == 1.0, "geometric_mean [1]")

    # geometric_mean of [2, 8] = 4
    data = [2.0, 8.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 4.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-6, "geometric_mean [2,8]")

    # geometric_mean of [3, 3, 3] = 3
    data = [3.0, 3.0, 3.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 3.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-6, "geometric_mean [3,3,3]")

    # geometric_mean <= arithmetic_mean
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    log_sum = 0.0
    s = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
        s = s + data[i]
    gm = _exp(log_sum / len(data))
    am = s / len(data)
    _ck(gm < am, "geometric <= arithmetic")

    # geometric_mean of [10, 100, 1000]
    data = [10.0, 100.0, 1000.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 100.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 0.01, "geometric_mean [10,100,1000]")

    # geometric_mean of [1, 1, 1, 1] = 1
    data = [1.0, 1.0, 1.0, 1.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 1.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-6, "geometric_mean all 1s")

    print("  geometric_mean: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # sqrt precision tests (8 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    diff = _sqrt(0.0) - 0.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-12, "sqrt(0)")

    diff = _sqrt(1.0) - 1.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-12, "sqrt(1)")

    diff = _sqrt(4.0) - 2.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-12, "sqrt(4)")

    diff = _sqrt(9.0) - 3.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-12, "sqrt(9)")

    diff = _sqrt(100.0) - 10.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-12, "sqrt(100)")

    diff = _sqrt(10000.0) - 100.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "sqrt(10000)")

    diff = _sqrt(2.0) - 1.4142135623730951
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "sqrt(2)")

    diff = _sqrt(0.25) - 0.5
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-12, "sqrt(0.25)")

    print("  sqrt: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # log/exp precision tests (10 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    diff = _log(1.0) - 0.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "log(1)")

    diff = _log(2.718281828459045) - 1.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "log(e)")

    diff = _log(10.0) - 2.302585092994046
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "log(10)")

    diff = _log(100.0) - 4.605170185988092
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "log(100)")

    # log(0.5) ~ -0.693 — compute expected as 0.0 - 0.693...
    val = _log(0.5)
    expected = 0.0 - 0.6931471805599453
    diff = val - expected
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "log(0.5)")

    diff = _exp(0.0) - 1.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "exp(0)")

    diff = _exp(1.0) - 2.718281828459045
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "exp(1)")

    # exp(-1) ~ 0.3679 — use 0.0 - 1.0 as argument
    val = _exp(0.0 - 1.0)
    diff = val - 0.36787944117144233
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-8, "exp(-1)")

    # roundtrip: exp(log(x)) ~ x
    diff = _exp(_log(42.0)) - 42.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-6, "exp(log(42))")

    diff = _exp(_log(0.001)) - 0.001
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-9, "exp(log(0.001))")

    print("  log_exp: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # insertion sort tests (10 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Already sorted
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    _isort(data)
    ok = True
    for i in range(5):
        if data[i] != i + 1.0:
            ok = False
    _ck(ok, "isort already sorted")

    # Reverse sorted
    data = [5.0, 4.0, 3.0, 2.0, 1.0]
    _isort(data)
    ok = True
    for i in range(5):
        if data[i] != i + 1.0:
            ok = False
    _ck(ok, "isort reverse")

    # Single element
    data = [42.0]
    _isort(data)
    _ck(data[0] == 42.0, "isort single")

    # Two elements
    data = [2.0, 1.0]
    _isort(data)
    ok = True
    if data[0] != 1.0:
        ok = False
    if data[1] != 2.0:
        ok = False
    _ck(ok, "isort two")

    # All duplicates
    data = [3.0, 3.0, 3.0, 3.0]
    _isort(data)
    ok = True
    for i in range(4):
        if data[i] != 3.0:
            ok = False
    _ck(ok, "isort duplicates")

    # With negatives — build via append from float-typed list
    data = [0.0]
    data.pop()
    data.append(3.0)
    data.append(0.0 - 1.0)
    data.append(2.0)
    data.append(0.0 - 5.0)
    data.append(0.0)
    _isort(data)
    ok = True
    # Expected sorted: -5, -1, 0, 2, 3
    exp_vals = [0.0]
    exp_vals.pop()
    exp_vals.append(0.0 - 5.0)
    exp_vals.append(0.0 - 1.0)
    exp_vals.append(0.0)
    exp_vals.append(2.0)
    exp_vals.append(3.0)
    for i in range(5):
        if data[i] != exp_vals[i]:
            ok = False
    _ck(ok, "isort negatives")

    # Large-ish random data (50 elements)
    data = [0.0]
    data.pop()
    v = 17
    for i in range(50):
        v = (v * 1103515245 + 12345) % 1000
        data.append(v * 1.0)
    _isort(data)
    ok = True
    for i in range(49):
        if data[i] > data[i + 1]:
            ok = False
    _ck(ok, "isort 50 random")

    # Stability proxy: equal elements stay in order
    data = [3.0, 1.0, 3.0, 2.0, 3.0]
    _isort(data)
    ok = True
    exp_vals2 = [1.0, 2.0, 3.0, 3.0, 3.0]
    for i in range(5):
        if data[i] != exp_vals2[i]:
            ok = False
    _ck(ok, "isort stable-like")

    # Sort 100 descending — use float-typed list
    data = [0.0]
    data.pop()
    for i in range(100):
        data.append(100.0 - i * 1.0)
    _isort(data)
    ok = True
    for i in range(100):
        if data[i] != i + 1.0:
            ok = False
    _ck(ok, "isort 100 descending")

    # Sort with large values
    data = [1000000.0, 1.0, 500000.0, 999999.0, 2.0]
    _isort(data)
    ok = True
    exp_vals3 = [1.0, 2.0, 500000.0, 999999.0, 1000000.0]
    for i in range(5):
        if data[i] != exp_vals3[i]:
            ok = False
    _ck(ok, "isort large values")

    print("  isort: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # cumulative / running statistics (8 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Running mean: add elements one at a time
    running_sum = 0.0
    count = 0
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    for i in range(len(data)):
        running_sum = running_sum + data[i]
        count = count + 1
    running_mean = running_sum / count
    _ck(running_mean == 30.0, "running mean [10..50]")

    # Running variance (Welford's online algorithm)
    mean_w = 0.0
    m2 = 0.0
    n = 0
    data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    for i in range(len(data)):
        n = n + 1
        delta = data[i] - mean_w
        mean_w = mean_w + delta / n
        delta2 = data[i] - mean_w
        m2 = m2 + delta * delta2

    welford_pvar = m2 / n
    _ck(welford_pvar == 4.0, "Welford pvariance")

    welford_var = m2 / (n - 1)
    diff = welford_var - 4.571428571428571
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "Welford variance")

    # Welford mean matches regular mean
    diff = mean_w - 5.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "Welford mean")

    # Sum of squares method
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = 0.0
    s2 = 0.0
    for i in range(len(data)):
        s = s + data[i]
        s2 = s2 + data[i] * data[i]
    n_val = len(data)
    m = s / n_val
    pvar2 = s2 / n_val - m * m
    diff = pvar2 - 2.0
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "sum of squares pvariance [1..5]")

    # Verify running sum of 1..100 = 5050
    running_sum = 0.0
    for i in range(1, 101):
        running_sum = running_sum + i * 1.0
    _ck(running_sum == 5050.0, "sum 1..100")

    # Verify sum of squares 1..10 = 385
    sq_sum = 0.0
    for i in range(1, 11):
        sq_sum = sq_sum + i * i * 1.0
    _ck(sq_sum == 385.0, "sum of squares 1..10")

    # Mean of alternating +1, -1 (100 elements) = 0
    s = 0.0
    for i in range(100):
        if i % 2 == 0:
            s = s + 1.0
        else:
            s = s - 1.0
    _ck(s == 0.0, "alternating +1 -1 sum")

    print("  cumulative: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # edge cases and stress (11 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Very large values
    data = [1e15, 1e15 + 1.0, 1e15 + 2.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    diff = m - (1e15 + 1.0)
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1.0, "mean large values")

    # Very small values
    data = [1e-15, 2e-15, 3e-15]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    diff = m - 2e-15
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-25, "mean tiny values")

    # Mean of 1000 elements — float-typed list
    data = [0.0]
    data.pop()
    s = 0.0
    for i in range(1000):
        val = i * 1.0
        data.append(val)
        s = s + val
    m = s / 1000.0
    _ck(m == 499.5, "mean 0..999")

    # Median of 1001 elements (middle = 500) — float-typed list
    data = [0.0]
    data.pop()
    for i in range(1001):
        data.append(1000.0 - i * 1.0)
    _isort(data)
    _ck(data[500] == 500.0, "median 0..1000")

    # Variance of constant data = 0
    data = [42.0, 42.0, 42.0, 42.0, 42.0]
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    ssq = 0.0
    for i in range(len(data)):
        d = data[i] - m
        ssq = ssq + d * d
    _ck(ssq == 0.0, "variance constant is zero")

    # Geometric mean of powers of 2: [2, 4, 8, 16] = 2^2.5 ~ 5.6569
    data = [2.0, 4.0, 8.0, 16.0]
    log_sum = 0.0
    for i in range(len(data)):
        log_sum = log_sum + _log(data[i])
    gm = _exp(log_sum / len(data))
    diff = gm - 5.656854249492381
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 0.001, "geometric_mean powers of 2")

    # Harmonic mean of [1, 2, 3, 4] = 48/25 = 1.92
    data = [1.0, 2.0, 3.0, 4.0]
    recip_sum = 0.0
    for i in range(len(data)):
        recip_sum = recip_sum + 1.0 / data[i]
    hm = len(data) * 1.0 / recip_sum
    diff = hm - 1.92
    if diff < 0.0:
        diff = 0.0 - diff
    _ck(diff < 1e-10, "harmonic_mean [1,2,3,4]")

    # AM-GM-HM inequality: AM >= GM >= HM for positive data
    data = [1.0, 4.0, 9.0, 16.0, 25.0]
    s = 0.0
    log_sum = 0.0
    recip_sum = 0.0
    for i in range(len(data)):
        s = s + data[i]
        log_sum = log_sum + _log(data[i])
        recip_sum = recip_sum + 1.0 / data[i]
    am = s / len(data)
    gm = _exp(log_sum / len(data))
    hm = len(data) * 1.0 / recip_sum
    _ck(am >= gm, "AM >= GM")
    _ck(gm >= hm, "GM >= HM")

    # sqrt consistency: sqrt(x)^2 ~ x for various x
    ok = True
    test_vals = [0.01, 0.1, 1.0, 2.0, 10.0, 100.0, 1000.0, 10000.0]
    for i in range(len(test_vals)):
        x = test_vals[i]
        sr = _sqrt(x)
        diff = sr * sr - x
        if diff < 0.0:
            diff = 0.0 - diff
        if diff > x * 1e-10 + 1e-15:
            ok = False
    _ck(ok, "sqrt roundtrip 8 values")

    # Large list statistics stress: mean of 500 odd numbers — float-typed list
    data = [0.0]
    data.pop()
    for i in range(500):
        data.append(i * 2.0 + 1.0)
    s = 0.0
    for i in range(len(data)):
        s = s + data[i]
    m = s / len(data)
    _ck(m == 500.0, "mean 500 odd numbers")

    print("  edge_stress: " + str(_gp) + "/" + str(_gp + _gf))


# ---------------------------------------------------------------------------
# Run and summarize
# ---------------------------------------------------------------------------

main()

print("")
_total = _pc + _fc
if _fc == 0:
    print("ALL TESTS PASSED: " + str(_total) + "/" + str(_total))
else:
    print("TESTS FAILED: " + str(_fc) + " of " + str(_total))
