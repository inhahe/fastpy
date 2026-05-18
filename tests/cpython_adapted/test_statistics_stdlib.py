# Auto-adapted from CPython Lib/test/test_statistics.py
# Tests fastpy's ability to compile and run the statistics module
# Stdlib source inlined from: C:\Users\inhah\AppData\Local\Python\pythoncore-3.13-64\Lib\statistics.py

# ======================================================================
# Inlined stdlib module: statistics
# ======================================================================

"""
Basic statistics module.

This module provides functions for calculating statistics of data, including
averages, variance, and standard deviation.

Calculating averages
--------------------

==================  ==================================================
Function            Description
==================  ==================================================
mean                Arithmetic mean (average) of data.
fmean               Fast, floating-point arithmetic mean.
geometric_mean      Geometric mean of data.
harmonic_mean       Harmonic mean of data.
median              Median (middle value) of data.
median_low          Low median of data.
median_high         High median of data.
median_grouped      Median, or 50th percentile, of grouped data.
mode                Mode (most common value) of data.
multimode           List of modes (most common values of data).
quantiles           Divide data into intervals with equal probability.
==================  ==================================================

Calculate the arithmetic mean ("the average") of data:

>>> mean([-1.0, 2.5, 3.25, 5.75])
2.625


Calculate the standard median of discrete data:

>>> median([2, 3, 4, 5])
3.5


Calculate the median, or 50th percentile, of data grouped into class intervals
centred on the data values provided. E.g. if your data points are rounded to
the nearest whole number:

>>> median_grouped([2, 2, 3, 3, 3, 4])  #doctest: +ELLIPSIS
2.8333333333...

This should be interpreted in this way: you have two data points in the class
interval 1.5-2.5, three data points in the class interval 2.5-3.5, and one in
the class interval 3.5-4.5. The median of these data points is 2.8333...


Calculating variability or spread
---------------------------------

==================  =============================================
Function            Description
==================  =============================================
pvariance           Population variance of data.
variance            Sample variance of data.
pstdev              Population standard deviation of data.
stdev               Sample standard deviation of data.
==================  =============================================

Calculate the standard deviation of sample data:

>>> stdev([2.5, 3.25, 5.5, 11.25, 11.75])  #doctest: +ELLIPSIS
4.38961843444...

If you have previously calculated the mean, you can pass it as the optional
second argument to the four "spread" functions to avoid recalculating it:

>>> data = [1, 2, 2, 4, 4, 4, 5, 6]
>>> mu = mean(data)
>>> pvariance(data, mu)
2.5


Statistics for relations between two inputs
-------------------------------------------

==================  ====================================================
Function            Description
==================  ====================================================
covariance          Sample covariance for two variables.
correlation         Pearson's correlation coefficient for two variables.
linear_regression   Intercept and slope for simple linear regression.
==================  ====================================================

Calculate covariance, Pearson's correlation, and simple linear regression
for two inputs:

>>> x = [1, 2, 3, 4, 5, 6, 7, 8, 9]
>>> y = [1, 2, 3, 1, 2, 3, 1, 2, 3]
>>> covariance(x, y)
0.75
>>> correlation(x, y)  #doctest: +ELLIPSIS
0.31622776601...
>>> linear_regression(x, y)  #doctest:
LinearRegression(slope=0.1, intercept=1.5)


Exceptions
----------

A single exception is defined: StatisticsError is a subclass of ValueError.

"""

__all__ = [
    'NormalDist',
    'StatisticsError',
    'correlation',
    'covariance',
    'fmean',
    'geometric_mean',
    'harmonic_mean',
    'kde',
    'kde_random',
    'linear_regression',
    'mean',
    'median',
    'median_grouped',
    'median_high',
    'median_low',
    'mode',
    'multimode',
    'pstdev',
    'pvariance',
    'quantiles',
    'stdev',
    'variance',
]

import math
import numbers
import random
import sys

from fractions import Fraction
from decimal import Decimal
from itertools import count, groupby, repeat
from bisect import bisect_left, bisect_right
from math import hypot, sqrt, fabs, exp, erf, tau, log, fsum, sumprod
from math import isfinite, isinf, pi, cos, sin, tan, cosh, asin, atan, acos
from functools import reduce
from operator import itemgetter
from collections import Counter, namedtuple, defaultdict

_SQRT2 = sqrt(2.0)
_random = random

# === Exceptions ===

class StatisticsError(ValueError):
    pass


# === Private utilities ===

def _sum(data):
    """_sum(data) -> (type, sum, count)

    Return a high-precision sum of the given numeric data as a fraction,
    together with the type to be converted to and the count of items.

    Examples
    --------

    >>> _sum([3, 2.25, 4.5, -0.5, 0.25])
    (<class 'float'>, Fraction(19, 2), 5)

    Some sources of round-off error will be avoided:

    # Built-in sum returns zero.
    >>> _sum([1e50, 1, -1e50] * 1000)
    (<class 'float'>, Fraction(1000, 1), 3000)

    Fractions and Decimals are also supported:

    >>> from fractions import Fraction as F
    >>> _sum([F(2, 3), F(7, 5), F(1, 4), F(5, 6)])
    (<class 'fractions.Fraction'>, Fraction(63, 20), 4)

    >>> from decimal import Decimal as D
    >>> data = [D("0.1375"), D("0.2108"), D("0.3061"), D("0.0419")]
    >>> _sum(data)
    (<class 'decimal.Decimal'>, Fraction(6963, 10000), 4)

    Mixed types are currently treated as an error, except that int is
    allowed.
    """
    count = 0
    types = set()
    types_add = types.add
    partials = {}
    partials_get = partials.get
    for typ, values in groupby(data, type):
        types_add(typ)
        for n, d in map(_exact_ratio, values):
            count += 1
            partials[d] = partials_get(d, 0) + n
    if None in partials:
        # The sum will be a NAN or INF. We can ignore all the finite
        # partials, and just look at this special one.
        total = partials[None]
        assert not _isfinite(total)
    else:
        # Sum all the partial sums using builtin sum.
        total = sum(Fraction(n, d) for d, n in partials.items())
    T = reduce(_coerce, types, int)  # or raise TypeError
    return (T, total, count)


def _ss(data, c=None):
    """Return the exact mean and sum of square deviations of sequence data.

    Calculations are done in a single pass, allowing the input to be an iterator.

    If given *c* is used the mean; otherwise, it is calculated from the data.
    Use the *c* argument with care, as it can lead to garbage results.

    """
    if c is not None:
        T, ssd, count = _sum((d := x - c) * d for x in data)
        return (T, ssd, c, count)
    count = 0
    types = set()
    types_add = types.add
    sx_partials = defaultdict(int)
    sxx_partials = defaultdict(int)
    for typ, values in groupby(data, type):
        types_add(typ)
        for n, d in map(_exact_ratio, values):
            count += 1
            sx_partials[d] += n
            sxx_partials[d] += n * n
    if not count:
        ssd = c = Fraction(0)
    elif None in sx_partials:
        # The sum will be a NAN or INF. We can ignore all the finite
        # partials, and just look at this special one.
        ssd = c = sx_partials[None]
        assert not _isfinite(ssd)
    else:
        sx = sum(Fraction(n, d) for d, n in sx_partials.items())
        sxx = sum(Fraction(n, d*d) for d, n in sxx_partials.items())
        # This formula has poor numeric properties for floats,
        # but with fractions it is exact.
        ssd = (count * sxx - sx * sx) / count
        c = sx / count
    T = reduce(_coerce, types, int)  # or raise TypeError
    return (T, ssd, c, count)


def _isfinite(x):
    try:
        return x.is_finite()  # Likely a Decimal.
    except AttributeError:
        return math.isfinite(x)  # Coerces to float first.


def _coerce(T, S):
    """Coerce types T and S to a common type, or raise TypeError.

    Coercion rules are currently an implementation detail. See the CoerceTest
    test class in test_statistics for details.
    """
    # See http://bugs.python.org/issue24068.
    assert T is not bool, "initial type T is bool"
    # If the types are the same, no need to coerce anything. Put this
    # first, so that the usual case (no coercion needed) happens as soon
    # as possible.
    if T is S:  return T
    # Mixed int & other coerce to the other type.
    if S is int or S is bool:  return T
    if T is int:  return S
    # If one is a (strict) subclass of the other, coerce to the subclass.
    if issubclass(S, T):  return S
    if issubclass(T, S):  return T
    # Ints coerce to the other type.
    if issubclass(T, int):  return S
    if issubclass(S, int):  return T
    # Mixed fraction & float coerces to float (or float subclass).
    if issubclass(T, Fraction) and issubclass(S, float):
        return S
    if issubclass(T, float) and issubclass(S, Fraction):
        return T
    # Any other combination is disallowed.
    msg = "don't know how to coerce %s and %s"
    raise TypeError(msg % (T.__name__, S.__name__))


def _exact_ratio(x):
    """Return Real number x to exact (numerator, denominator) pair.

    >>> _exact_ratio(0.25)
    (1, 4)

    x is expected to be an int, Fraction, Decimal or float.
    """

    # XXX We should revisit whether using fractions to accumulate exact
    # ratios is the right way to go.

    # The integer ratios for binary floats can have numerators or
    # denominators with over 300 decimal digits.  The problem is more
    # acute with decimal floats where the default decimal context
    # supports a huge range of exponents from Emin=-999999 to
    # Emax=999999.  When expanded with as_integer_ratio(), numbers like
    # Decimal('3.14E+5000') and Decimal('3.14E-5000') have large
    # numerators or denominators that will slow computation.

    # When the integer ratios are accumulated as fractions, the size
    # grows to cover the full range from the smallest magnitude to the
    # largest.  For example, Fraction(3.14E+300) + Fraction(3.14E-300),
    # has a 616 digit numerator.  Likewise,
    # Fraction(Decimal('3.14E+5000')) + Fraction(Decimal('3.14E-5000'))
    # has 10,003 digit numerator.

    # This doesn't seem to have been problem in practice, but it is a
    # potential pitfall.

    try:
        return x.as_integer_ratio()
    except AttributeError:
        pass
    except (OverflowError, ValueError):
        # float NAN or INF.
        assert not _isfinite(x)
        return (x, None)
    try:
        # x may be an Integral ABC.
        return (x.numerator, x.denominator)
    except AttributeError:
        msg = f"can't convert type '{type(x).__name__}' to numerator/denominator"
        raise TypeError(msg)


def _convert(value, T):
    """Convert value to given numeric type T."""
    if type(value) is T:
        # This covers the cases where T is Fraction, or where value is
        # a NAN or INF (Decimal or float).
        return value
    if issubclass(T, int) and value.denominator != 1:
        T = float
    try:
        # FIXME: what do we do if this overflows?
        return T(value)
    except TypeError:
        if issubclass(T, Decimal):
            return T(value.numerator) / T(value.denominator)
        else:
            raise


def _fail_neg(values, errmsg='negative value'):
    """Iterate over values, failing if any are less than zero."""
    for x in values:
        if x < 0:
            raise StatisticsError(errmsg)
        yield x


def _rank(data, /, *, key=None, reverse=False, ties='average', start=1) -> list[float]:
    """Rank order a dataset. The lowest value has rank 1.

    Ties are averaged so that equal values receive the same rank:

        >>> data = [31, 56, 31, 25, 75, 18]
        >>> _rank(data)
        [3.5, 5.0, 3.5, 2.0, 6.0, 1.0]

    The operation is idempotent:

        >>> _rank([3.5, 5.0, 3.5, 2.0, 6.0, 1.0])
        [3.5, 5.0, 3.5, 2.0, 6.0, 1.0]

    It is possible to rank the data in reverse order so that the
    highest value has rank 1.  Also, a key-function can extract
    the field to be ranked:

        >>> goals = [('eagles', 45), ('bears', 48), ('lions', 44)]
        >>> _rank(goals, key=itemgetter(1), reverse=True)
        [2.0, 1.0, 3.0]

    Ranks are conventionally numbered starting from one; however,
    setting *start* to zero allows the ranks to be used as array indices:

        >>> prize = ['Gold', 'Silver', 'Bronze', 'Certificate']
        >>> scores = [8.1, 7.3, 9.4, 8.3]
        >>> [prize[int(i)] for i in _rank(scores, start=0, reverse=True)]
        ['Bronze', 'Certificate', 'Gold', 'Silver']

    """
    # If this function becomes public at some point, more thought
    # needs to be given to the signature.  A list of ints is
    # plausible when ties is "min" or "max".  When ties is "average",
    # either list[float] or list[Fraction] is plausible.

    # Default handling of ties matches scipy.stats.mstats.spearmanr.
    if ties != 'average':
        raise ValueError(f'Unknown tie resolution method: {ties!r}')
    if key is not None:
        data = map(key, data)
    val_pos = sorted(zip(data, count()), reverse=reverse)
    i = start - 1
    result = [0] * len(val_pos)
    for _, g in groupby(val_pos, key=itemgetter(0)):
        group = list(g)
        size = len(group)
        rank = i + (size + 1) / 2
        for value, orig_pos in group:
            result[orig_pos] = rank
        i += size
    return result


def _integer_sqrt_of_frac_rto(n: int, m: int) -> int:
    """Square root of n/m, rounded to the nearest integer using round-to-odd."""
    # Reference: https://www.lri.fr/~melquion/doc/05-imacs17_1-expose.pdf
    a = math.isqrt(n // m)
    return a | (a*a*m != n)


# For 53 bit precision floats, the bit width used in
# _float_sqrt_of_frac() is 109.
_sqrt_bit_width: int = 2 * sys.float_info.mant_dig + 3


def _float_sqrt_of_frac(n: int, m: int) -> float:
    """Square root of n/m as a float, correctly rounded."""
    # See principle and proof sketch at: https://bugs.python.org/msg407078
    q = (n.bit_length() - m.bit_length() - _sqrt_bit_width) // 2
    if q >= 0:
        numerator = _integer_sqrt_of_frac_rto(n, m << 2 * q) << q
        denominator = 1
    else:
        numerator = _integer_sqrt_of_frac_rto(n << -2 * q, m)
        denominator = 1 << -q
    return numerator / denominator   # Convert to float


def _decimal_sqrt_of_frac(n: int, m: int) -> Decimal:
    """Square root of n/m as a Decimal, correctly rounded."""
    # Premise:  For decimal, computing (n/m).sqrt() can be off
    #           by 1 ulp from the correctly rounded result.
    # Method:   Check the result, moving up or down a step if needed.
    if n <= 0:
        if not n:
            return Decimal('0.0')
        n, m = -n, -m

    root = (Decimal(n) / Decimal(m)).sqrt()
    nr, dr = root.as_integer_ratio()

    plus = root.next_plus()
    np, dp = plus.as_integer_ratio()
    # test: n / m > ((root + plus) / 2) ** 2
    if 4 * n * (dr*dp)**2 > m * (dr*np + dp*nr)**2:
        return plus

    minus = root.next_minus()
    nm, dm = minus.as_integer_ratio()
    # test: n / m < ((root + minus) / 2) ** 2
    if 4 * n * (dr*dm)**2 < m * (dr*nm + dm*nr)**2:
        return minus

    return root


# === Measures of central tendency (averages) ===

def mean(data):
    """Return the sample arithmetic mean of data.

    >>> mean([1, 2, 3, 4, 4])
    2.8

    >>> from fractions import Fraction as F
    >>> mean([F(3, 7), F(1, 21), F(5, 3), F(1, 3)])
    Fraction(13, 21)

    >>> from decimal import Decimal as D
    >>> mean([D("0.5"), D("0.75"), D("0.625"), D("0.375")])
    Decimal('0.5625')

    If ``data`` is empty, StatisticsError will be raised.
    """
    T, total, n = _sum(data)
    if n < 1:
        raise StatisticsError('mean requires at least one data point')
    return _convert(total / n, T)


def fmean(data, weights=None):
    """Convert data to floats and compute the arithmetic mean.

    This runs faster than the mean() function and it always returns a float.
    If the input dataset is empty, it raises a StatisticsError.

    >>> fmean([3.5, 4.0, 5.25])
    4.25
    """
    if weights is None:
        try:
            n = len(data)
        except TypeError:
            # Handle iterators that do not define __len__().
            n = 0
            def count(iterable):
                nonlocal n
                for n, x in enumerate(iterable, start=1):
                    yield x
            data = count(data)
        total = fsum(data)
        if not n:
            raise StatisticsError('fmean requires at least one data point')
        return total / n
    if not isinstance(weights, (list, tuple)):
        weights = list(weights)
    try:
        num = sumprod(data, weights)
    except ValueError:
        raise StatisticsError('data and weights must be the same length')
    den = fsum(weights)
    if not den:
        raise StatisticsError('sum of weights must be non-zero')
    return num / den


def geometric_mean(data):
    """Convert data to floats and compute the geometric mean.

    Raises a StatisticsError if the input dataset is empty
    or if it contains a negative value.

    Returns zero if the product of inputs is zero.

    No special efforts are made to achieve exact results.
    (However, this may change in the future.)

    >>> round(geometric_mean([54, 24, 36]), 9)
    36.0
    """
    n = 0
    found_zero = False
    def count_positive(iterable):
        nonlocal n, found_zero
        for n, x in enumerate(iterable, start=1):
            if x > 0.0 or math.isnan(x):
                yield x
            elif x == 0.0:
                found_zero = True
            else:
                raise StatisticsError('No negative inputs allowed', x)
    total = fsum(map(log, count_positive(data)))
    if not n:
        raise StatisticsError('Must have a non-empty dataset')
    if math.isnan(total):
        return math.nan
    if found_zero:
        return math.nan if total == math.inf else 0.0
    return exp(total / n)


def harmonic_mean(data, weights=None):
    """Return the harmonic mean of data.

    The harmonic mean is the reciprocal of the arithmetic mean of the
    reciprocals of the data.  It can be used for averaging ratios or
    rates, for example speeds.

    Suppose a car travels 40 km/hr for 5 km and then speeds-up to
    60 km/hr for another 5 km. What is the average speed?

        >>> harmonic_mean([40, 60])
        48.0

    Suppose a car travels 40 km/hr for 5 km, and when traffic clears,
    speeds-up to 60 km/hr for the remaining 30 km of the journey. What
    is the average speed?

        >>> harmonic_mean([40, 60], weights=[5, 30])
        56.0

    If ``data`` is empty, or any element is less than zero,
    ``harmonic_mean`` will raise ``StatisticsError``.
    """
    if iter(data) is data:
        data = list(data)
    errmsg = 'harmonic mean does not support negative values'
    n = len(data)
    if n < 1:
        raise StatisticsError('harmonic_mean requires at least one data point')
    elif n == 1 and weights is None:
        x = data[0]
        if isinstance(x, (numbers.Real, Decimal)):
            if x < 0:
                raise StatisticsError(errmsg)
            return x
        else:
            raise TypeError('unsupported type')
    if weights is None:
        weights = repeat(1, n)
        sum_weights = n
    else:
        if iter(weights) is weights:
            weights = list(weights)
        if len(weights) != n:
            raise StatisticsError('Number of weights does not match data size')
        _, sum_weights, _ = _sum(w for w in _fail_neg(weights, errmsg))
    try:
        data = _fail_neg(data, errmsg)
        T, total, count = _sum(w / x if w else 0 for w, x in zip(weights, data))
    except ZeroDivisionError:
        return 0
    if total <= 0:
        raise StatisticsError('Weighted sum must be positive')
    return _convert(sum_weights / total, T)

# FIXME: investigate ways to calculate medians without sorting? Quickselect?
def median(data):
    """Return the median (middle value) of numeric data.

    When the number of data points is odd, return the middle data point.
    When the number of data points is even, the median is interpolated by
    taking the average of the two middle values:

    >>> median([1, 3, 5])
    3
    >>> median([1, 3, 5, 7])
    4.0

    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError("no median for empty data")
    if n % 2 == 1:
        return data[n // 2]
    else:
        i = n // 2
        return (data[i - 1] + data[i]) / 2


def median_low(data):
    """Return the low median of numeric data.

    When the number of data points is odd, the middle value is returned.
    When it is even, the smaller of the two middle values is returned.

    >>> median_low([1, 3, 5])
    3
    >>> median_low([1, 3, 5, 7])
    3

    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError("no median for empty data")
    if n % 2 == 1:
        return data[n // 2]
    else:
        return data[n // 2 - 1]


def median_high(data):
    """Return the high median of data.

    When the number of data points is odd, the middle value is returned.
    When it is even, the larger of the two middle values is returned.

    >>> median_high([1, 3, 5])
    3
    >>> median_high([1, 3, 5, 7])
    5

    """
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError("no median for empty data")
    return data[n // 2]


def median_grouped(data, interval=1.0):
    """Estimates the median for numeric data binned around the midpoints
    of consecutive, fixed-width intervals.

    The *data* can be any iterable of numeric data with each value being
    exactly the midpoint of a bin.  At least one value must be present.

    The *interval* is width of each bin.

    For example, demographic information may have been summarized into
    consecutive ten-year age groups with each group being represented
    by the 5-year midpoints of the intervals:

        >>> demographics = Counter({
        ...    25: 172,   # 20 to 30 years old
        ...    35: 484,   # 30 to 40 years old
        ...    45: 387,   # 40 to 50 years old
        ...    55:  22,   # 50 to 60 years old
        ...    65:   6,   # 60 to 70 years old
        ... })

    The 50th percentile (median) is the 536th person out of the 1071
    member cohort.  That person is in the 30 to 40 year old age group.

    The regular median() function would assume that everyone in the
    tricenarian age group was exactly 35 years old.  A more tenable
    assumption is that the 484 members of that age group are evenly
    distributed between 30 and 40.  For that, we use median_grouped().

        >>> data = list(demographics.elements())
        >>> median(data)
        35
        >>> round(median_grouped(data, interval=10), 1)
        37.5

    The caller is responsible for making sure the data points are separated
    by exact multiples of *interval*.  This is essential for getting a
    correct result.  The function does not check this precondition.

    Inputs may be any numeric type that can be coerced to a float during
    the interpolation step.

    """
    data = sorted(data)
    n = len(data)
    if not n:
        raise StatisticsError("no median for empty data")

    # Find the value at the midpoint. Remember this corresponds to the
    # midpoint of the class interval.
    x = data[n // 2]

    # Using O(log n) bisection, find where all the x values occur in the data.
    # All x will lie within data[i:j].
    i = bisect_left(data, x)
    j = bisect_right(data, x, lo=i)

    # Coerce to floats, raising a TypeError if not possible
    try:
        interval = float(interval)
        x = float(x)
    except ValueError:
        raise TypeError(f'Value cannot be converted to a float')

    # Interpolate the median using the formula found at:
    # https://www.cuemath.com/data/median-of-grouped-data/
    L = x - interval / 2.0    # Lower limit of the median interval
    cf = i                    # Cumulative frequency of the preceding interval
    f = j - i                 # Number of elements in the median internal
    return L + interval * (n / 2 - cf) / f


def mode(data):
    """Return the most common data point from discrete or nominal data.

    ``mode`` assumes discrete data, and returns a single value. This is the
    standard treatment of the mode as commonly taught in schools:

        >>> mode([1, 1, 2, 3, 3, 3, 3, 4])
        3

    This also works with nominal (non-numeric) data:

        >>> mode(["red", "blue", "blue", "red", "green", "red", "red"])
        'red'

    If there are multiple modes with same frequency, return the first one
    encountered:

        >>> mode(['red', 'red', 'green', 'blue', 'blue'])
        'red'

    If *data* is empty, ``mode``, raises StatisticsError.

    """
    pairs = Counter(iter(data)).most_common(1)
    try:
        return pairs[0][0]
    except IndexError:
        raise StatisticsError('no mode for empty data') from None


def multimode(data):
    """Return a list of the most frequently occurring values.

    Will return more than one result if there are multiple modes
    or an empty list if *data* is empty.

    >>> multimode('aabbbbbbbbcc')
    ['b']
    >>> multimode('aabbbbccddddeeffffgg')
    ['b', 'd', 'f']
    >>> multimode('')
    []
    """
    counts = Counter(iter(data))
    if not counts:
        return []
    maxcount = max(counts.values())
    return [value for value, count in counts.items() if count == maxcount]


def kde(data, h, kernel='normal', *, cumulative=False):
    """Kernel Density Estimation:  Create a continuous probability density
    function or cumulative distribution function from discrete samples.

    The basic idea is to smooth the data using a kernel function
    to help draw inferences about a population from a sample.

    The degree of smoothing is controlled by the scaling parameter h
    which is called the bandwidth.  Smaller values emphasize local
    features while larger values give smoother results.

    The kernel determines the relative weights of the sample data
    points.  Generally, the choice of kernel shape does not matter
    as much as the more influential bandwidth smoothing parameter.

    Kernels that give some weight to every sample point:

       normal (gauss)
       logistic
       sigmoid

    Kernels that only give weight to sample points within
    the bandwidth:

       rectangular (uniform)
       triangular
       parabolic (epanechnikov)
       quartic (biweight)
       triweight
       cosine

    If *cumulative* is true, will return a cumulative distribution function.

    A StatisticsError will be raised if the data sequence is empty.

    Example
    -------

    Given a sample of six data points, construct a continuous
    function that estimates the underlying probability density:

        >>> sample = [-2.1, -1.3, -0.4, 1.9, 5.1, 6.2]
        >>> f_hat = kde(sample, h=1.5)

    Compute the area under the curve:

        >>> area = sum(f_hat(x) for x in range(-20, 20))
        >>> round(area, 4)
        1.0

    Plot the estimated probability density function at
    evenly spaced points from -6 to 10:

        >>> for x in range(-6, 11):
        ...     density = f_hat(x)
        ...     plot = ' ' * int(density * 400) + 'x'
        ...     print(f'{x:2}: {density:.3f} {plot}')
        ...
        -6: 0.002 x
        -5: 0.009    x
        -4: 0.031             x
        -3: 0.070                             x
        -2: 0.111                                             x
        -1: 0.125                                                   x
         0: 0.110                                            x
         1: 0.086                                   x
         2: 0.068                            x
         3: 0.059                        x
         4: 0.066                           x
         5: 0.082                                 x
         6: 0.082                                 x
         7: 0.058                        x
         8: 0.028            x
         9: 0.009    x
        10: 0.002 x

    Estimate P(4.5 < X <= 7.5), the probability that a new sample value
    will be between 4.5 and 7.5:

        >>> cdf = kde(sample, h=1.5, cumulative=True)
        >>> round(cdf(7.5) - cdf(4.5), 2)
        0.22

    References
    ----------

    Kernel density estimation and its application:
    https://www.itm-conferences.org/articles/itmconf/pdf/2018/08/itmconf_sam2018_00037.pdf

    Kernel functions in common use:
    https://en.wikipedia.org/wiki/Kernel_(statistics)#kernel_functions_in_common_use

    Interactive graphical demonstration and exploration:
    https://demonstrations.wolfram.com/KernelDensityEstimation/

    Kernel estimation of cumulative distribution function of a random variable with bounded support
    https://www.econstor.eu/bitstream/10419/207829/1/10.21307_stattrans-2016-037.pdf

    """

    n = len(data)
    if not n:
        raise StatisticsError('Empty data sequence')

    if not isinstance(data[0], (int, float)):
        raise TypeError('Data sequence must contain ints or floats')

    if h <= 0.0:
        raise StatisticsError(f'Bandwidth h must be positive, not {h=!r}')

    match kernel:

        case 'normal' | 'gauss':
            sqrt2pi = sqrt(2 * pi)
            sqrt2 = sqrt(2)
            K = lambda t: exp(-1/2 * t * t) / sqrt2pi
            W = lambda t: 1/2 * (1.0 + erf(t / sqrt2))
            support = None

        case 'logistic':
            # 1.0 / (exp(t) + 2.0 + exp(-t))
            K = lambda t: 1/2 / (1.0 + cosh(t))
            W = lambda t: 1.0 - 1.0 / (exp(t) + 1.0)
            support = None

        case 'sigmoid':
            # (2/pi) / (exp(t) + exp(-t))
            c1 = 1 / pi
            c2 = 2 / pi
            K = lambda t: c1 / cosh(t)
            W = lambda t: c2 * atan(exp(t))
            support = None

        case 'rectangular' | 'uniform':
            K = lambda t: 1/2
            W = lambda t: 1/2 * t + 1/2
            support = 1.0

        case 'triangular':
            K = lambda t: 1.0 - abs(t)
            W = lambda t: t*t * (1/2 if t < 0.0 else -1/2) + t + 1/2
            support = 1.0

        case 'parabolic' | 'epanechnikov':
            K = lambda t: 3/4 * (1.0 - t * t)
            W = lambda t: -1/4 * t**3 + 3/4 * t + 1/2
            support = 1.0

        case 'quartic' | 'biweight':
            K = lambda t: 15/16 * (1.0 - t * t) ** 2
            W = lambda t: 3/16 * t**5 - 5/8 * t**3 + 15/16 * t + 1/2
            support = 1.0

        case 'triweight':
            K = lambda t: 35/32 * (1.0 - t * t) ** 3
            W = lambda t: 35/32 * (-1/7*t**7 + 3/5*t**5 - t**3 + t) + 1/2
            support = 1.0

        case 'cosine':
            c1 = pi / 4
            c2 = pi / 2
            K = lambda t: c1 * cos(c2 * t)
            W = lambda t: 1/2 * sin(c2 * t) + 1/2
            support = 1.0

        case _:
            raise StatisticsError(f'Unknown kernel name: {kernel!r}')

    if support is None:

        def pdf(x):
            n = len(data)
            return sum(K((x - x_i) / h) for x_i in data) / (n * h)

        def cdf(x):
            n = len(data)
            return sum(W((x - x_i) / h) for x_i in data) / n

    else:

        sample = sorted(data)
        bandwidth = h * support

        def pdf(x):
            nonlocal n, sample
            if len(data) != n:
                sample = sorted(data)
                n = len(data)
            i = bisect_left(sample, x - bandwidth)
            j = bisect_right(sample, x + bandwidth)
            supported = sample[i : j]
            return sum(K((x - x_i) / h) for x_i in supported) / (n * h)

        def cdf(x):
            nonlocal n, sample
            if len(data) != n:
                sample = sorted(data)
                n = len(data)
            i = bisect_left(sample, x - bandwidth)
            j = bisect_right(sample, x + bandwidth)
            supported = sample[i : j]
            return sum((W((x - x_i) / h) for x_i in supported), i) / n

    if cumulative:
        cdf.__doc__ = f'CDF estimate with {h=!r} and {kernel=!r}'
        return cdf

    else:
        pdf.__doc__ = f'PDF estimate with {h=!r} and {kernel=!r}'
        return pdf


# Notes on methods for computing quantiles
# ----------------------------------------
#
# There is no one perfect way to compute quantiles.  Here we offer
# two methods that serve common needs.  Most other packages
# surveyed offered at least one or both of these two, making them
# "standard" in the sense of "widely-adopted and reproducible".
# They are also easy to explain, easy to compute manually, and have
# straight-forward interpretations that aren't surprising.

# The default method is known as "R6", "PERCENTILE.EXC", or "expected
# value of rank order statistics". The alternative method is known as
# "R7", "PERCENTILE.INC", or "mode of rank order statistics".

# For sample data where there is a positive probability for values
# beyond the range of the data, the R6 exclusive method is a
# reasonable choice.  Consider a random sample of nine values from a
# population with a uniform distribution from 0.0 to 1.0.  The
# distribution of the third ranked sample point is described by
# betavariate(alpha=3, beta=7) which has mode=0.250, median=0.286, and
# mean=0.300.  Only the latter (which corresponds with R6) gives the
# desired cut point with 30% of the population falling below that
# value, making it comparable to a result from an inv_cdf() function.
# The R6 exclusive method is also idempotent.

# For describing population data where the end points are known to
# be included in the data, the R7 inclusive method is a reasonable
# choice.  Instead of the mean, it uses the mode of the beta
# distribution for the interior points.  Per Hyndman & Fan, "One nice
# property is that the vertices of Q7(p) divide the range into n - 1
# intervals, and exactly 100p% of the intervals lie to the left of
# Q7(p) and 100(1 - p)% of the intervals lie to the right of Q7(p)."

# If needed, other methods could be added.  However, for now, the
# position is that fewer options make for easier choices and that
# external packages can be used for anything more advanced.

def quantiles(data, *, n=4, method='exclusive'):
    """Divide *data* into *n* continuous intervals with equal probability.

    Returns a list of (n - 1) cut points separating the intervals.

    Set *n* to 4 for quartiles (the default).  Set *n* to 10 for deciles.
    Set *n* to 100 for percentiles which gives the 99 cuts points that
    separate *data* in to 100 equal sized groups.

    The *data* can be any iterable containing sample.
    The cut points are linearly interpolated between data points.

    If *method* is set to *inclusive*, *data* is treated as population
    data.  The minimum value is treated as the 0th percentile and the
    maximum value is treated as the 100th percentile.
    """
    if n < 1:
        raise StatisticsError('n must be at least 1')
    data = sorted(data)
    ld = len(data)
    if ld < 2:
        if ld == 1:
            return data * (n - 1)
        raise StatisticsError('must have at least one data point')

    if method == 'inclusive':
        m = ld - 1
        result = []
        for i in range(1, n):
            j, delta = divmod(i * m, n)
            interpolated = (data[j] * (n - delta) + data[j + 1] * delta) / n
            result.append(interpolated)
        return result

    if method == 'exclusive':
        m = ld + 1
        result = []
        for i in range(1, n):
            j = i * m // n                               # rescale i to m/n
            j = 1 if j < 1 else ld-1 if j > ld-1 else j  # clamp to 1 .. ld-1
            delta = i*m - j*n                            # exact integer math
            interpolated = (data[j - 1] * (n - delta) + data[j] * delta) / n
            result.append(interpolated)
        return result

    raise ValueError(f'Unknown method: {method!r}')


# === Measures of spread ===

# See http://mathworld.wolfram.com/Variance.html
#     http://mathworld.wolfram.com/SampleVariance.html


def variance(data, xbar=None):
    """Return the sample variance of data.

    data should be an iterable of Real-valued numbers, with at least two
    values. The optional argument xbar, if given, should be the mean of
    the data. If it is missing or None, the mean is automatically calculated.

    Use this function when your data is a sample from a population. To
    calculate the variance from the entire population, see ``pvariance``.

    Examples:

    >>> data = [2.75, 1.75, 1.25, 0.25, 0.5, 1.25, 3.5]
    >>> variance(data)
    1.3720238095238095

    If you have already calculated the mean of your data, you can pass it as
    the optional second argument ``xbar`` to avoid recalculating it:

    >>> m = mean(data)
    >>> variance(data, m)
    1.3720238095238095

    This function does not check that ``xbar`` is actually the mean of
    ``data``. Giving arbitrary values for ``xbar`` may lead to invalid or
    impossible results.

    Decimals and Fractions are supported:

    >>> from decimal import Decimal as D
    >>> variance([D("27.5"), D("30.25"), D("30.25"), D("34.5"), D("41.75")])
    Decimal('31.01875')

    >>> from fractions import Fraction as F
    >>> variance([F(1, 6), F(1, 2), F(5, 3)])
    Fraction(67, 108)

    """
    T, ss, c, n = _ss(data, xbar)
    if n < 2:
        raise StatisticsError('variance requires at least two data points')
    return _convert(ss / (n - 1), T)


def pvariance(data, mu=None):
    """Return the population variance of ``data``.

    data should be a sequence or iterable of Real-valued numbers, with at least one
    value. The optional argument mu, if given, should be the mean of
    the data. If it is missing or None, the mean is automatically calculated.

    Use this function to calculate the variance from the entire population.
    To estimate the variance from a sample, the ``variance`` function is
    usually a better choice.

    Examples:

    >>> data = [0.0, 0.25, 0.25, 1.25, 1.5, 1.75, 2.75, 3.25]
    >>> pvariance(data)
    1.25

    If you have already calculated the mean of the data, you can pass it as
    the optional second argument to avoid recalculating it:

    >>> mu = mean(data)
    >>> pvariance(data, mu)
    1.25

    Decimals and Fractions are supported:

    >>> from decimal import Decimal as D
    >>> pvariance([D("27.5"), D("30.25"), D("30.25"), D("34.5"), D("41.75")])
    Decimal('24.815')

    >>> from fractions import Fraction as F
    >>> pvariance([F(1, 4), F(5, 4), F(1, 2)])
    Fraction(13, 72)

    """
    T, ss, c, n = _ss(data, mu)
    if n < 1:
        raise StatisticsError('pvariance requires at least one data point')
    return _convert(ss / n, T)


def stdev(data, xbar=None):
    """Return the square root of the sample variance.

    See ``variance`` for arguments and other details.

    >>> stdev([1.5, 2.5, 2.5, 2.75, 3.25, 4.75])
    1.0810874155219827

    """
    T, ss, c, n = _ss(data, xbar)
    if n < 2:
        raise StatisticsError('stdev requires at least two data points')
    mss = ss / (n - 1)
    try:
        mss_numerator = mss.numerator
        mss_denominator = mss.denominator
    except AttributeError:
        raise ValueError('inf or nan encountered in data')
    if issubclass(T, Decimal):
        return _decimal_sqrt_of_frac(mss_numerator, mss_denominator)
    return _float_sqrt_of_frac(mss_numerator, mss_denominator)


def pstdev(data, mu=None):
    """Return the square root of the population variance.

    See ``pvariance`` for arguments and other details.

    >>> pstdev([1.5, 2.5, 2.5, 2.75, 3.25, 4.75])
    0.986893273527251

    """
    T, ss, c, n = _ss(data, mu)
    if n < 1:
        raise StatisticsError('pstdev requires at least one data point')
    mss = ss / n
    try:
        mss_numerator = mss.numerator
        mss_denominator = mss.denominator
    except AttributeError:
        raise ValueError('inf or nan encountered in data')
    if issubclass(T, Decimal):
        return _decimal_sqrt_of_frac(mss_numerator, mss_denominator)
    return _float_sqrt_of_frac(mss_numerator, mss_denominator)


def _mean_stdev(data):
    """In one pass, compute the mean and sample standard deviation as floats."""
    T, ss, xbar, n = _ss(data)
    if n < 2:
        raise StatisticsError('stdev requires at least two data points')
    mss = ss / (n - 1)
    try:
        return float(xbar), _float_sqrt_of_frac(mss.numerator, mss.denominator)
    except AttributeError:
        # Handle Nans and Infs gracefully
        return float(xbar), float(xbar) / float(ss)

def _sqrtprod(x: float, y: float) -> float:
    "Return sqrt(x * y) computed with improved accuracy and without overflow/underflow."
    h = sqrt(x * y)
    if not isfinite(h):
        if isinf(h) and not isinf(x) and not isinf(y):
            # Finite inputs overflowed, so scale down, and recompute.
            scale = 2.0 ** -512  # sqrt(1 / sys.float_info.max)
            return _sqrtprod(scale * x, scale * y) / scale
        return h
    if not h:
        if x and y:
            # Non-zero inputs underflowed, so scale up, and recompute.
            # Scale:  1 / sqrt(sys.float_info.min * sys.float_info.epsilon)
            scale = 2.0 ** 537
            return _sqrtprod(scale * x, scale * y) / scale
        return h
    # Improve accuracy with a differential correction.
    # https://www.wolframalpha.com/input/?i=Maclaurin+series+sqrt%28h**2+%2B+x%29+at+x%3D0
    d = sumprod((x, h), (y, -h))
    return h + d / (2.0 * h)


# === Statistics for relations between two inputs ===

# See https://en.wikipedia.org/wiki/Covariance
#     https://en.wikipedia.org/wiki/Pearson_correlation_coefficient
#     https://en.wikipedia.org/wiki/Simple_linear_regression


def covariance(x, y, /):
    """Covariance

    Return the sample covariance of two inputs *x* and *y*. Covariance
    is a measure of the joint variability of two inputs.

    >>> x = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    >>> y = [1, 2, 3, 1, 2, 3, 1, 2, 3]
    >>> covariance(x, y)
    0.75
    >>> z = [9, 8, 7, 6, 5, 4, 3, 2, 1]
    >>> covariance(x, z)
    -7.5
    >>> covariance(z, x)
    -7.5

    """
    n = len(x)
    if len(y) != n:
        raise StatisticsError('covariance requires that both inputs have same number of data points')
    if n < 2:
        raise StatisticsError('covariance requires at least two data points')
    xbar = fsum(x) / n
    ybar = fsum(y) / n
    sxy = sumprod((xi - xbar for xi in x), (yi - ybar for yi in y))
    return sxy / (n - 1)


def correlation(x, y, /, *, method='linear'):
    """Pearson's correlation coefficient

    Return the Pearson's correlation coefficient for two inputs. Pearson's
    correlation coefficient *r* takes values between -1 and +1. It measures
    the strength and direction of a linear relationship.

    >>> x = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    >>> y = [9, 8, 7, 6, 5, 4, 3, 2, 1]
    >>> correlation(x, x)
    1.0
    >>> correlation(x, y)
    -1.0

    If *method* is "ranked", computes Spearman's rank correlation coefficient
    for two inputs.  The data is replaced by ranks.  Ties are averaged
    so that equal values receive the same rank.  The resulting coefficient
    measures the strength of a monotonic relationship.

    Spearman's rank correlation coefficient is appropriate for ordinal
    data or for continuous data that doesn't meet the linear proportion
    requirement for Pearson's correlation coefficient.
    """
    n = len(x)
    if len(y) != n:
        raise StatisticsError('correlation requires that both inputs have same number of data points')
    if n < 2:
        raise StatisticsError('correlation requires at least two data points')
    if method not in {'linear', 'ranked'}:
        raise ValueError(f'Unknown method: {method!r}')
    if method == 'ranked':
        start = (n - 1) / -2            # Center rankings around zero
        x = _rank(x, start=start)
        y = _rank(y, start=start)
    else:
        xbar = fsum(x) / n
        ybar = fsum(y) / n
        x = [xi - xbar for xi in x]
        y = [yi - ybar for yi in y]
    sxy = sumprod(x, y)
    sxx = sumprod(x, x)
    syy = sumprod(y, y)
    try:
        return sxy / _sqrtprod(sxx, syy)
    except ZeroDivisionError:
        raise StatisticsError('at least one of the inputs is constant')


LinearRegression = namedtuple('LinearRegression', ('slope', 'intercept'))


def linear_regression(x, y, /, *, proportional=False):
    """Slope and intercept for simple linear regression.

    Return the slope and intercept of simple linear regression
    parameters estimated using ordinary least squares. Simple linear
    regression describes relationship between an independent variable
    *x* and a dependent variable *y* in terms of a linear function:

        y = slope * x + intercept + noise

    where *slope* and *intercept* are the regression parameters that are
    estimated, and noise represents the variability of the data that was
    not explained by the linear regression (it is equal to the
    difference between predicted and actual values of the dependent
    variable).

    The parameters are returned as a named tuple.

    >>> x = [1, 2, 3, 4, 5]
    >>> noise = NormalDist().samples(5, seed=42)
    >>> y = [3 * x[i] + 2 + noise[i] for i in range(5)]
    >>> linear_regression(x, y)  #doctest: +ELLIPSIS
    LinearRegression(slope=3.17495..., intercept=1.00925...)

    If *proportional* is true, the independent variable *x* and the
    dependent variable *y* are assumed to be directly proportional.
    The data is fit to a line passing through the origin.

    Since the *intercept* will always be 0.0, the underlying linear
    function simplifies to:

        y = slope * x + noise

    >>> y = [3 * x[i] + noise[i] for i in range(5)]
    >>> linear_regression(x, y, proportional=True)  #doctest: +ELLIPSIS
    LinearRegression(slope=2.90475..., intercept=0.0)

    """
    n = len(x)
    if len(y) != n:
        raise StatisticsError('linear regression requires that both inputs have same number of data points')
    if n < 2:
        raise StatisticsError('linear regression requires at least two data points')
    if not proportional:
        xbar = fsum(x) / n
        ybar = fsum(y) / n
        x = [xi - xbar for xi in x]  # List because used three times below
        y = (yi - ybar for yi in y)  # Generator because only used once below
    sxy = sumprod(x, y) + 0.0        # Add zero to coerce result to a float
    sxx = sumprod(x, x)
    try:
        slope = sxy / sxx   # equivalent to:  covariance(x, y) / variance(x)
    except ZeroDivisionError:
        raise StatisticsError('x is constant')
    intercept = 0.0 if proportional else ybar - slope * xbar
    return LinearRegression(slope=slope, intercept=intercept)


## Normal Distribution #####################################################


def _normal_dist_inv_cdf(p, mu, sigma):
    # There is no closed-form solution to the inverse CDF for the normal
    # distribution, so we use a rational approximation instead:
    # Wichura, M.J. (1988). "Algorithm AS241: The Percentage Points of the
    # Normal Distribution".  Applied Statistics. Blackwell Publishing. 37
    # (3): 477–484. doi:10.2307/2347330. JSTOR 2347330.
    q = p - 0.5
    if fabs(q) <= 0.425:
        r = 0.180625 - q * q
        # Hash sum: 55.88319_28806_14901_4439
        num = (((((((2.50908_09287_30122_6727e+3 * r +
                     3.34305_75583_58812_8105e+4) * r +
                     6.72657_70927_00870_0853e+4) * r +
                     4.59219_53931_54987_1457e+4) * r +
                     1.37316_93765_50946_1125e+4) * r +
                     1.97159_09503_06551_4427e+3) * r +
                     1.33141_66789_17843_7745e+2) * r +
                     3.38713_28727_96366_6080e+0) * q
        den = (((((((5.22649_52788_52854_5610e+3 * r +
                     2.87290_85735_72194_2674e+4) * r +
                     3.93078_95800_09271_0610e+4) * r +
                     2.12137_94301_58659_5867e+4) * r +
                     5.39419_60214_24751_1077e+3) * r +
                     6.87187_00749_20579_0830e+2) * r +
                     4.23133_30701_60091_1252e+1) * r +
                     1.0)
        x = num / den
        return mu + (x * sigma)
    r = p if q <= 0.0 else 1.0 - p
    r = sqrt(-log(r))
    if r <= 5.0:
        r = r - 1.6
        # Hash sum: 49.33206_50330_16102_89036
        num = (((((((7.74545_01427_83414_07640e-4 * r +
                     2.27238_44989_26918_45833e-2) * r +
                     2.41780_72517_74506_11770e-1) * r +
                     1.27045_82524_52368_38258e+0) * r +
                     3.64784_83247_63204_60504e+0) * r +
                     5.76949_72214_60691_40550e+0) * r +
                     4.63033_78461_56545_29590e+0) * r +
                     1.42343_71107_49683_57734e+0)
        den = (((((((1.05075_00716_44416_84324e-9 * r +
                     5.47593_80849_95344_94600e-4) * r +
                     1.51986_66563_61645_71966e-2) * r +
                     1.48103_97642_74800_74590e-1) * r +
                     6.89767_33498_51000_04550e-1) * r +
                     1.67638_48301_83803_84940e+0) * r +
                     2.05319_16266_37758_82187e+0) * r +
                     1.0)
    else:
        r = r - 5.0
        # Hash sum: 47.52583_31754_92896_71629
        num = (((((((2.01033_43992_92288_13265e-7 * r +
                     2.71155_55687_43487_57815e-5) * r +
                     1.24266_09473_88078_43860e-3) * r +
                     2.65321_89526_57612_30930e-2) * r +
                     2.96560_57182_85048_91230e-1) * r +
                     1.78482_65399_17291_33580e+0) * r +
                     5.46378_49111_64114_36990e+0) * r +
                     6.65790_46435_01103_77720e+0)
        den = (((((((2.04426_31033_89939_78564e-15 * r +
                     1.42151_17583_16445_88870e-7) * r +
                     1.84631_83175_10054_68180e-5) * r +
                     7.86869_13114_56132_59100e-4) * r +
                     1.48753_61290_85061_48525e-2) * r +
                     1.36929_88092_27358_05310e-1) * r +
                     5.99832_20655_58879_37690e-1) * r +
                     1.0)
    x = num / den
    if q < 0.0:
        x = -x
    return mu + (x * sigma)


# If available, use C implementation
try:
    from _statistics import _normal_dist_inv_cdf
except ImportError:
    pass


class NormalDist:
    "Normal distribution of a random variable"
    # https://en.wikipedia.org/wiki/Normal_distribution
    # https://en.wikipedia.org/wiki/Variance#Properties

    __slots__ = {
        '_mu': 'Arithmetic mean of a normal distribution',
        '_sigma': 'Standard deviation of a normal distribution',
    }

    def __init__(self, mu=0.0, sigma=1.0):
        "NormalDist where mu is the mean and sigma is the standard deviation."
        if sigma < 0.0:
            raise StatisticsError('sigma must be non-negative')
        self._mu = float(mu)
        self._sigma = float(sigma)

    @classmethod
    def from_samples(cls, data):
        "Make a normal distribution instance from sample data."
        return cls(*_mean_stdev(data))

    def samples(self, n, *, seed=None):
        "Generate *n* samples for a given mean and standard deviation."
        rnd = random.random if seed is None else random.Random(seed).random
        inv_cdf = _normal_dist_inv_cdf
        mu = self._mu
        sigma = self._sigma
        return [inv_cdf(rnd(), mu, sigma) for _ in repeat(None, n)]

    def pdf(self, x):
        "Probability density function.  P(x <= X < x+dx) / dx"
        variance = self._sigma * self._sigma
        if not variance:
            raise StatisticsError('pdf() not defined when sigma is zero')
        diff = x - self._mu
        return exp(diff * diff / (-2.0 * variance)) / sqrt(tau * variance)

    def cdf(self, x):
        "Cumulative distribution function.  P(X <= x)"
        if not self._sigma:
            raise StatisticsError('cdf() not defined when sigma is zero')
        return 0.5 * (1.0 + erf((x - self._mu) / (self._sigma * _SQRT2)))

    def inv_cdf(self, p):
        """Inverse cumulative distribution function.  x : P(X <= x) = p

        Finds the value of the random variable such that the probability of
        the variable being less than or equal to that value equals the given
        probability.

        This function is also called the percent point function or quantile
        function.
        """
        if p <= 0.0 or p >= 1.0:
            raise StatisticsError('p must be in the range 0.0 < p < 1.0')
        return _normal_dist_inv_cdf(p, self._mu, self._sigma)

    def quantiles(self, n=4):
        """Divide into *n* continuous intervals with equal probability.

        Returns a list of (n - 1) cut points separating the intervals.

        Set *n* to 4 for quartiles (the default).  Set *n* to 10 for deciles.
        Set *n* to 100 for percentiles which gives the 99 cuts points that
        separate the normal distribution in to 100 equal sized groups.
        """
        return [self.inv_cdf(i / n) for i in range(1, n)]

    def overlap(self, other):
        """Compute the overlapping coefficient (OVL) between two normal distributions.

        Measures the agreement between two normal probability distributions.
        Returns a value between 0.0 and 1.0 giving the overlapping area in
        the two underlying probability density functions.

            >>> N1 = NormalDist(2.4, 1.6)
            >>> N2 = NormalDist(3.2, 2.0)
            >>> N1.overlap(N2)
            0.8035050657330205
        """
        # See: "The overlapping coefficient as a measure of agreement between
        # probability distributions and point estimation of the overlap of two
        # normal densities" -- Henry F. Inman and Edwin L. Bradley Jr
        # http://dx.doi.org/10.1080/03610928908830127
        if not isinstance(other, NormalDist):
            raise TypeError('Expected another NormalDist instance')
        X, Y = self, other
        if (Y._sigma, Y._mu) < (X._sigma, X._mu):  # sort to assure commutativity
            X, Y = Y, X
        X_var, Y_var = X.variance, Y.variance
        if not X_var or not Y_var:
            raise StatisticsError('overlap() not defined when sigma is zero')
        dv = Y_var - X_var
        dm = fabs(Y._mu - X._mu)
        if not dv:
            return 1.0 - erf(dm / (2.0 * X._sigma * _SQRT2))
        a = X._mu * Y_var - Y._mu * X_var
        b = X._sigma * Y._sigma * sqrt(dm * dm + dv * log(Y_var / X_var))
        x1 = (a + b) / dv
        x2 = (a - b) / dv
        return 1.0 - (fabs(Y.cdf(x1) - X.cdf(x1)) + fabs(Y.cdf(x2) - X.cdf(x2)))

    def zscore(self, x):
        """Compute the Standard Score.  (x - mean) / stdev

        Describes *x* in terms of the number of standard deviations
        above or below the mean of the normal distribution.
        """
        # https://www.statisticshowto.com/probability-and-statistics/z-score/
        if not self._sigma:
            raise StatisticsError('zscore() not defined when sigma is zero')
        return (x - self._mu) / self._sigma

    @property
    def mean(self):
        "Arithmetic mean of the normal distribution."
        return self._mu

    @property
    def median(self):
        "Return the median of the normal distribution"
        return self._mu

    @property
    def mode(self):
        """Return the mode of the normal distribution

        The mode is the value x where which the probability density
        function (pdf) takes its maximum value.
        """
        return self._mu

    @property
    def stdev(self):
        "Standard deviation of the normal distribution."
        return self._sigma

    @property
    def variance(self):
        "Square of the standard deviation."
        return self._sigma * self._sigma

    def __add__(x1, x2):
        """Add a constant or another NormalDist instance.

        If *other* is a constant, translate mu by the constant,
        leaving sigma unchanged.

        If *other* is a NormalDist, add both the means and the variances.
        Mathematically, this works only if the two distributions are
        independent or if they are jointly normally distributed.
        """
        if isinstance(x2, NormalDist):
            return NormalDist(x1._mu + x2._mu, hypot(x1._sigma, x2._sigma))
        return NormalDist(x1._mu + x2, x1._sigma)

    def __sub__(x1, x2):
        """Subtract a constant or another NormalDist instance.

        If *other* is a constant, translate by the constant mu,
        leaving sigma unchanged.

        If *other* is a NormalDist, subtract the means and add the variances.
        Mathematically, this works only if the two distributions are
        independent or if they are jointly normally distributed.
        """
        if isinstance(x2, NormalDist):
            return NormalDist(x1._mu - x2._mu, hypot(x1._sigma, x2._sigma))
        return NormalDist(x1._mu - x2, x1._sigma)

    def __mul__(x1, x2):
        """Multiply both mu and sigma by a constant.

        Used for rescaling, perhaps to change measurement units.
        Sigma is scaled with the absolute value of the constant.
        """
        return NormalDist(x1._mu * x2, x1._sigma * fabs(x2))

    def __truediv__(x1, x2):
        """Divide both mu and sigma by a constant.

        Used for rescaling, perhaps to change measurement units.
        Sigma is scaled with the absolute value of the constant.
        """
        return NormalDist(x1._mu / x2, x1._sigma / fabs(x2))

    def __pos__(x1):
        "Return a copy of the instance."
        return NormalDist(x1._mu, x1._sigma)

    def __neg__(x1):
        "Negates mu while keeping sigma the same."
        return NormalDist(-x1._mu, x1._sigma)

    __radd__ = __add__

    def __rsub__(x1, x2):
        "Subtract a NormalDist from a constant or another NormalDist."
        return -(x1 - x2)

    __rmul__ = __mul__

    def __eq__(x1, x2):
        "Two NormalDist objects are equal if their mu and sigma are both equal."
        if not isinstance(x2, NormalDist):
            return NotImplemented
        return x1._mu == x2._mu and x1._sigma == x2._sigma

    def __hash__(self):
        "NormalDist objects hash equal if their mu and sigma are both equal."
        return hash((self._mu, self._sigma))

    def __repr__(self):
        return f'{type(self).__name__}(mu={self._mu!r}, sigma={self._sigma!r})'

    def __getstate__(self):
        return self._mu, self._sigma

    def __setstate__(self, state):
        self._mu, self._sigma = state


## kde_random() ##############################################################

def _newton_raphson(f_inv_estimate, f, f_prime, tolerance=1e-12):
    def f_inv(y):
        "Return x such that f(x) ≈ y within the specified tolerance."
        x = f_inv_estimate(y)
        while abs(diff := f(x) - y) > tolerance:
            x -= diff / f_prime(x)
        return x
    return f_inv

def _quartic_invcdf_estimate(p):
    sign, p = (1.0, p) if p <= 1/2 else (-1.0, 1.0 - p)
    x = (2.0 * p) ** 0.4258865685331 - 1.0
    if p >= 0.004 < 0.499:
        x += 0.026818732 * sin(7.101753784 * p + 2.73230839482953)
    return x * sign

_quartic_invcdf = _newton_raphson(
    f_inv_estimate = _quartic_invcdf_estimate,
    f = lambda t: 3/16 * t**5 - 5/8 * t**3 + 15/16 * t + 1/2,
    f_prime = lambda t: 15/16 * (1.0 - t * t) ** 2)

def _triweight_invcdf_estimate(p):
    sign, p = (1.0, p) if p <= 1/2 else (-1.0, 1.0 - p)
    x = (2.0 * p) ** 0.3400218741872791 - 1.0
    return x * sign

_triweight_invcdf = _newton_raphson(
    f_inv_estimate = _triweight_invcdf_estimate,
    f = lambda t: 35/32 * (-1/7*t**7 + 3/5*t**5 - t**3 + t) + 1/2,
    f_prime = lambda t: 35/32 * (1.0 - t * t) ** 3)

_kernel_invcdfs = {
    'normal': NormalDist().inv_cdf,
    'logistic': lambda p: log(p / (1 - p)),
    'sigmoid': lambda p: log(tan(p * pi/2)),
    'rectangular': lambda p: 2*p - 1,
    'parabolic': lambda p: 2 * cos((acos(2*p-1) + pi) / 3),
    'quartic': _quartic_invcdf,
    'triweight': _triweight_invcdf,
    'triangular': lambda p: sqrt(2*p) - 1 if p < 1/2 else 1 - sqrt(2 - 2*p),
    'cosine': lambda p: 2 * asin(2*p - 1) / pi,
}
_kernel_invcdfs['gauss'] = _kernel_invcdfs['normal']
_kernel_invcdfs['uniform'] = _kernel_invcdfs['rectangular']
_kernel_invcdfs['epanechnikov'] = _kernel_invcdfs['parabolic']
_kernel_invcdfs['biweight'] = _kernel_invcdfs['quartic']

def kde_random(data, h, kernel='normal', *, seed=None):
    """Return a function that makes a random selection from the estimated
    probability density function created by kde(data, h, kernel).

    Providing a *seed* allows reproducible selections within a single
    thread.  The seed may be an integer, float, str, or bytes.

    A StatisticsError will be raised if the *data* sequence is empty.

    Example:

    >>> data = [-2.1, -1.3, -0.4, 1.9, 5.1, 6.2]
    >>> rand = kde_random(data, h=1.5, seed=8675309)
    >>> new_selections = [rand() for i in range(10)]
    >>> [round(x, 1) for x in new_selections]
    [0.7, 6.2, 1.2, 6.9, 7.0, 1.8, 2.5, -0.5, -1.8, 5.6]

    """
    n = len(data)
    if not n:
        raise StatisticsError('Empty data sequence')

    if not isinstance(data[0], (int, float)):
        raise TypeError('Data sequence must contain ints or floats')

    if h <= 0.0:
        raise StatisticsError(f'Bandwidth h must be positive, not {h=!r}')

    kernel_invcdf = _kernel_invcdfs.get(kernel)
    if kernel_invcdf is None:
        raise StatisticsError(f'Unknown kernel name: {kernel!r}')

    prng = _random.Random(seed)
    random = prng.random
    choice = prng.choice

    def rand():
        return choice(data) + h * kernel_invcdf(random())

    rand.__doc__ = f'Random KDE selection with {h=!r} and {kernel=!r}'

    return rand

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

def sign(x):
    """Return -1.0 for negatives, including -0.0, otherwise +1.0."""
    return math.copysign(1, x)

def _nan_equal(a, b):
    """Return True if a and b are both the same kind of NAN.

    >>> _nan_equal(Decimal('NAN'), Decimal('NAN'))
    True
    >>> _nan_equal(Decimal('sNAN'), Decimal('sNAN'))
    True
    >>> _nan_equal(Decimal('NAN'), Decimal('sNAN'))
    False
    >>> _nan_equal(Decimal(42), Decimal('NAN'))
    False

    >>> _nan_equal(float('NAN'), float('NAN'))
    True
    >>> _nan_equal(float('NAN'), 0.5)
    False

    >>> _nan_equal(float('NAN'), Decimal('NAN'))
    False

    NAN payloads are not compared.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return math.isnan(a) and math.isnan(b)
    aexp = a.as_tuple()[2]
    bexp = b.as_tuple()[2]
    return aexp == bexp and aexp in ('n', 'N')

def _calc_errors(actual, expected):
    """Return the absolute and relative errors between two numbers.

    >>> _calc_errors(100, 75)
    (25, 0.25)
    >>> _calc_errors(100, 100)
    (0, 0.0)

    Returns the (absolute error, relative error) between the two arguments.
    """
    base = max(abs(actual), abs(expected))
    abs_err = abs(actual - expected)
    rel_err = abs_err / base if base else float('inf')
    return (abs_err, rel_err)

def approx_equal(x, y, tol=1e-12, rel=1e-07):
    """approx_equal(x, y [, tol [, rel]]) => True|False

    Return True if numbers x and y are approximately equal, to within some
    margin of error, otherwise return False. Numbers which compare equal
    will also compare approximately equal.

    x is approximately equal to y if the difference between them is less than
    an absolute error tol or a relative error rel, whichever is bigger.

    If given, both tol and rel must be finite, non-negative numbers. If not
    given, default values are tol=1e-12 and rel=1e-7.

    >>> approx_equal(1.2589, 1.2587, tol=0.0003, rel=0)
    True
    >>> approx_equal(1.2589, 1.2587, tol=0.0001, rel=0)
    False

    Absolute error is defined as abs(x-y); if that is less than or equal to
    tol, x and y are considered approximately equal.

    Relative error is defined as abs((x-y)/x) or abs((x-y)/y), whichever is
    smaller, provided x or y are not zero. If that figure is less than or
    equal to rel, x and y are considered approximately equal.

    Complex numbers are not directly supported. If you wish to compare to
    complex numbers, extract their real and imaginary parts and compare them
    individually.

    NANs always compare unequal, even with themselves. Infinities compare
    approximately equal if they have the same sign (both positive or both
    negative). Infinities with different signs compare unequal; so do
    comparisons of infinities with finite numbers.
    """
    if tol < 0 or rel < 0:
        raise ValueError('error tolerances must be non-negative')
    if math.isnan(x) or math.isnan(y):
        return False
    if x == y:
        return True
    if math.isinf(x) or math.isinf(y):
        return False
    actual_error = abs(x - y)
    allowed_error = max(tol, rel * max(abs(x), abs(y)))
    return actual_error <= allowed_error

class _DoNothing:
    """
    When doing numeric work, especially with floats, exact equality is often
    not what you want. Due to round-off error, it is often a bad idea to try
    to compare floats with equality. Instead the usual procedure is to test
    them with some (hopefully small!) allowance for error.

    The ``approx_equal`` function allows you to specify either an absolute
    error tolerance, or a relative error, or both.

    Absolute error tolerances are simple, but you need to know the magnitude
    of the quantities being compared:

    >>> approx_equal(12.345, 12.346, tol=1e-3)
    True
    >>> approx_equal(12.345e6, 12.346e6, tol=1e-3)  # tol is too small.
    False

    Relative errors are more suitable when the values you are comparing can
    vary in magnitude:

    >>> approx_equal(12.345, 12.346, rel=1e-4)
    True
    >>> approx_equal(12.345e6, 12.346e6, rel=1e-4)
    True

    but a naive implementation of relative error testing can run into trouble
    around zero.

    If you supply both an absolute tolerance and a relative error, the
    comparison succeeds if either individual test succeeds:

    >>> approx_equal(12.345e6, 12.346e6, tol=1e-3, rel=1e-4)
    True

    """
    pass

class UnivariateCommonMixin:

    def test_no_args(self):
        self.assertRaises(TypeError, self.func)

    def test_empty_data(self):
        for empty in ([], (), iter([])):
            self.assertRaises(statistics.StatisticsError, self.func, empty)

    def prepare_data(self):
        """Return int data for various tests."""
        data = list(range(10))
        while data == sorted(data):
            random.shuffle(data)
        return data

    def test_no_inplace_modifications(self):
        data = self.prepare_data()
        assert len(data) != 1
        assert data != sorted(data)
        saved = data[:]
        assert data is not saved
        _ = self.func(data)
        self.assertListEqual(data, saved, 'data has been modified')

    def test_order_doesnt_matter(self):
        data = [1, 2, 3, 3, 3, 4, 5, 6] * 100
        expected = self.func(data)
        random.shuffle(data)
        actual = self.func(data)
        self.assertEqual(expected, actual)

    def test_type_of_data_collection(self):

        class MyList(list):
            pass

        class MyTuple(tuple):
            pass

        def generator(data):
            return (obj for obj in data)
        data = self.prepare_data()
        expected = self.func(data)
        for kind in (list, tuple, iter, MyList, MyTuple, generator):
            result = self.func(kind(data))
            self.assertEqual(result, expected)

    def test_range_data(self):
        data = range(20, 50, 3)
        expected = self.func(list(data))
        self.assertEqual(self.func(data), expected)

    def test_bad_arg_types(self):
        self.check_for_type_error(None)
        self.check_for_type_error(23)
        self.check_for_type_error(42.0)
        self.check_for_type_error(object())

    def check_for_type_error(self, *args):
        self.assertRaises(TypeError, self.func, *args)

    def test_type_of_data_element(self):

        class MyFloat(float):

            def __truediv__(self, other):
                return type(self)(super().__truediv__(other))

            def __add__(self, other):
                return type(self)(super().__add__(other))
            __radd__ = __add__
        raw = self.prepare_data()
        expected = self.func(raw)
        for kind in (float, MyFloat, Decimal, Fraction):
            data = [kind(x) for x in raw]
            result = type(expected)(self.func(data))
            self.assertEqual(result, expected)

class UnivariateTypeMixin:
    """Mixin class for type-conserving functions.

    This mixin class holds test(s) for functions which conserve the type of
    individual data points. E.g. the mean of a list of Fractions should itself
    be a Fraction.

    Not all tests to do with types need go in this class. Only those that
    rely on the function returning the same type as its input data.
    """

    def prepare_types_for_conservation_test(self):
        """Return the types which are expected to be conserved."""

        class MyFloat(float):

            def __truediv__(self, other):
                return type(self)(super().__truediv__(other))

            def __rtruediv__(self, other):
                return type(self)(super().__rtruediv__(other))

            def __sub__(self, other):
                return type(self)(super().__sub__(other))

            def __rsub__(self, other):
                return type(self)(super().__rsub__(other))

            def __pow__(self, other):
                return type(self)(super().__pow__(other))

            def __add__(self, other):
                return type(self)(super().__add__(other))
            __radd__ = __add__

            def __mul__(self, other):
                return type(self)(super().__mul__(other))
            __rmul__ = __mul__
        return (float, Decimal, Fraction, MyFloat)

    def test_types_conserved(self):
        data = self.prepare_data()
        for kind in self.prepare_types_for_conservation_test():
            d = [kind(x) for x in data]
            result = self.func(d)
            self.assertIs(type(result), kind)

class AverageMixin(UnivariateCommonMixin):

    def test_single_value(self):
        for x in (23, 42.5, 1300000000000000.0, Fraction(15, 19), Decimal('0.28')):
            self.assertEqual(self.func([x]), x)

    def prepare_values_for_repeated_single_test(self):
        return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

    def test_repeated_single_value(self):
        for x in self.prepare_values_for_repeated_single_test():
            for count in (2, 5, 10, 20):
                with self.subTest(x=x, count=count):
                    data = [x] * count
                    self.assertEqual(self.func(data), x)

class VarianceStdevMixin(UnivariateCommonMixin):
    rel = 1e-12

    def test_single_value(self):
        for x in (11, 19.8, 460000000000000.0, Fraction(21, 34), Decimal('8.392')):
            self.assertEqual(self.func([x]), 0)

    def test_repeated_single_value(self):
        for x in (7.2, 49, 8100000000000000.0, Fraction(3, 7), Decimal('62.4802')):
            for count in (2, 3, 5, 15):
                data = [x] * count
                self.assertEqual(self.func(data), 0)

    def test_domain_error_regression(self):
        data = [0.123456789012345] * 10000
        result = self.func(data)
        self.assertApproxEqual(result, 0.0, tol=5e-17)
        self.assertGreaterEqual(result, 0)

    def test_shift_data(self):
        raw = [1.03, 1.27, 1.94, 2.04, 2.58, 3.14, 4.75, 4.98, 5.42, 6.78]
        expected = self.func(raw)
        shift = 100000.0
        data = [x + shift for x in raw]
        self.assertApproxEqual(self.func(data), expected)

    def test_shift_data_exact(self):
        raw = [1, 3, 3, 4, 5, 7, 9, 10, 11, 16]
        assert all((x == int(x) for x in raw))
        expected = self.func(raw)
        shift = 10 ** 9
        data = [x + shift for x in raw]
        self.assertEqual(self.func(data), expected)

    def test_iter_list_same(self):
        data = [random.uniform(-3, 8) for _ in range(1000)]
        expected = self.func(data)
        self.assertEqual(self.func(iter(data)), expected)

def load_tests(loader, tests, ignore):
    """Used for doctest/unittest integration."""
    tests.addTests(doctest.DocTestSuite())
    tests.addTests(doctest.DocTestSuite(statistics))
    return tests


# ======================================================================
# Test functions (extracted from CPython test suite)
# ======================================================================

# Test functions from TestModules
def TestModules__test_py_functions():
    for fname in func_names:
        assertEqual(getattr(py_statistics, fname).__module__, 'statistics')


# Helper methods from ApproxEqualSymmetryTest
def do_relative_symmetry(a, b):
    a, b = (min(a, b), max(a, b))
    assert a < b
    delta = b - a
    rel_err1, rel_err2 = (abs(delta / a), abs(delta / b))
    rel = (rel_err1 + rel_err2) / 2
    assertTrue(approx_equal(a, b, tol=0, rel=rel))
    assertTrue(approx_equal(b, a, tol=0, rel=rel))

def do_symmetry_test(a, b, tol, rel):
    template = "approx_equal comparisons don't match for %r"
    flag1 = approx_equal(a, b, tol, rel)
    flag2 = approx_equal(b, a, tol, rel)
    assertEqual(flag1, flag2, template.format((a, b, tol, rel)))

# Test functions from ApproxEqualSymmetryTest
def ApproxEqualSymmetryTest__test_relative_symmetry():
    args1 = [2456, 37.8, -12.45, Decimal('2.54'), Fraction(17, 54)]
    args2 = [2459, 37.2, -12.41, Decimal('2.59'), Fraction(15, 54)]
    assert len(args1) == len(args2)
    for a, b in zip(args1, args2):
        do_relative_symmetry(a, b)

def ApproxEqualSymmetryTest__test_symmetry():
    args = [-23, -2, 5, 107, 93568]
    delta = 2
    for a in args:
        for type_ in (int, float, Decimal, Fraction):
            x = type_(a) * 100
            y = x + delta
            r = abs(delta / max(x, y))
            do_symmetry_test(x, y, tol=delta, rel=r)
            do_symmetry_test(x, y, tol=delta + 1, rel=2 * r)
            do_symmetry_test(x, y, tol=delta - 1, rel=r / 2)
            do_symmetry_test(x, y, tol=delta, rel=r / 2)
            do_symmetry_test(x, y, tol=delta - 1, rel=r)
            do_symmetry_test(x, y, tol=delta - 1, rel=2 * r)
            do_symmetry_test(x, x, tol=0, rel=0)
            do_symmetry_test(x, y, tol=0, rel=0)


# Helper methods from ApproxEqualExactTest
def do_exactly_equal_test(x, tol, rel):
    result = approx_equal(x, x, tol=tol, rel=rel)
    assertTrue(result, 'equality failure for x=%r' % x)
    result = approx_equal(-x, -x, tol=tol, rel=rel)
    assertTrue(result, 'equality failure for x=%r' % -x)

# Test functions from ApproxEqualExactTest
def ApproxEqualExactTest__test_exactly_equal_ints():
    for n in [42, 19740, 14974, 230, 1795, 700245, 36587]:
        do_exactly_equal_test(n, 0, 0)

def ApproxEqualExactTest__test_exactly_equal_floats():
    for x in [0.42, 1.974, 1497.4, 23.0, 179.5, 70.0245, 36.587]:
        do_exactly_equal_test(x, 0, 0)

def ApproxEqualExactTest__test_exactly_equal_fractions():
    F = Fraction
    for f in [F(1, 2), F(0), F(5, 3), F(9, 7), F(35, 36), F(3, 7)]:
        do_exactly_equal_test(f, 0, 0)

def ApproxEqualExactTest__test_exactly_equal_decimals():
    D = Decimal
    for d in map(D, '8.2 31.274 912.04 16.745 1.2047'.split()):
        do_exactly_equal_test(d, 0, 0)

def ApproxEqualExactTest__test_exactly_equal_absolute():
    for n in [16, 1013, 1372, 1198, 971, 4]:
        do_exactly_equal_test(n, 0.01, 0)
        do_exactly_equal_test(n / 10, 0.01, 0)
        f = Fraction(n, 1234)
        do_exactly_equal_test(f, 0.01, 0)

def ApproxEqualExactTest__test_exactly_equal_absolute_decimals():
    do_exactly_equal_test(Decimal('3.571'), Decimal('0.01'), 0)
    do_exactly_equal_test(-Decimal('81.3971'), Decimal('0.01'), 0)

def ApproxEqualExactTest__test_exactly_equal_relative():
    for x in [8347, 101.3, -7910.28, Fraction(5, 21)]:
        do_exactly_equal_test(x, 0, 0.01)
    do_exactly_equal_test(Decimal('11.68'), 0, Decimal('0.01'))

def ApproxEqualExactTest__test_exactly_equal_both():
    for x in [41017, 16.742, -813.02, Fraction(3, 8)]:
        do_exactly_equal_test(x, 0.1, 0.01)
    D = Decimal
    do_exactly_equal_test(D('7.2'), D('0.1'), D('0.01'))


# Helper methods from ApproxEqualUnequalTest
def do_exactly_unequal_test(x):
    for a in (x, -x):
        result = approx_equal(a, a + 1, tol=0, rel=0)
        assertFalse(result, 'inequality failure for x=%r' % a)

# Test functions from ApproxEqualUnequalTest
def ApproxEqualUnequalTest__test_exactly_unequal_ints():
    for n in [951, 572305, 478, 917, 17240]:
        do_exactly_unequal_test(n)

def ApproxEqualUnequalTest__test_exactly_unequal_floats():
    for x in [9.51, 5723.05, 47.8, 9.17, 17.24]:
        do_exactly_unequal_test(x)

def ApproxEqualUnequalTest__test_exactly_unequal_fractions():
    F = Fraction
    for f in [F(1, 5), F(7, 9), F(12, 11), F(101, 99023)]:
        do_exactly_unequal_test(f)

def ApproxEqualUnequalTest__test_exactly_unequal_decimals():
    for d in map(Decimal, '3.1415 298.12 3.47 18.996 0.00245'.split()):
        do_exactly_unequal_test(d)


# Helper methods from ApproxEqualInexactTest
def do_approx_equal_abs_test(x, delta):
    template = 'Test failure for x={!r}, y={!r}'
    for y in (x + delta, x - delta):
        msg = template.format(x, y)
        assertTrue(approx_equal(x, y, tol=2 * delta, rel=0), msg)
        assertFalse(approx_equal(x, y, tol=delta / 2, rel=0), msg)

def do_approx_equal_rel_test(x, delta):
    template = 'Test failure for x={!r}, y={!r}'
    for y in (x * (1 + delta), x * (1 - delta)):
        msg = template.format(x, y)
        assertTrue(approx_equal(x, y, tol=0, rel=2 * delta), msg)
        assertFalse(approx_equal(x, y, tol=0, rel=delta / 2), msg)

def do_check_both(a, b, tol, rel, tol_flag, rel_flag):
    check = assertTrue if tol_flag else assertFalse
    check(approx_equal(a, b, tol=tol, rel=0))
    check = assertTrue if rel_flag else assertFalse
    check(approx_equal(a, b, tol=0, rel=rel))
    check = assertTrue if tol_flag or rel_flag else assertFalse
    check(approx_equal(a, b, tol=tol, rel=rel))

# Test functions from ApproxEqualInexactTest
def ApproxEqualInexactTest__test_approx_equal_absolute_ints():
    for n in [-10737, -1975, -7, -2, 0, 1, 9, 37, 423, 9874, 23789110]:
        do_approx_equal_abs_test(n, 10)
        do_approx_equal_abs_test(n, 2)

def ApproxEqualInexactTest__test_approx_equal_absolute_floats():
    for x in [-284.126, -97.1, -3.4, -2.15, 0.5, 1.0, 7.8, 4.23, 3817.4]:
        do_approx_equal_abs_test(x, 1.5)
        do_approx_equal_abs_test(x, 0.01)
        do_approx_equal_abs_test(x, 0.0001)

def ApproxEqualInexactTest__test_approx_equal_absolute_fractions():
    delta = Fraction(1, 29)
    numerators = [-84, -15, -2, -1, 0, 1, 5, 17, 23, 34, 71]
    for f in (Fraction(n, 29) for n in numerators):
        do_approx_equal_abs_test(f, delta)
        do_approx_equal_abs_test(f, float(delta))

def ApproxEqualInexactTest__test_approx_equal_absolute_decimals():
    delta = Decimal('0.01')
    for d in map(Decimal, '1.0 3.5 36.08 61.79 7912.3648'.split()):
        do_approx_equal_abs_test(d, delta)
        do_approx_equal_abs_test(-d, delta)

def ApproxEqualInexactTest__test_cross_zero():
    assertTrue(approx_equal(1e-05, -1e-05, tol=0.0001, rel=0))

def ApproxEqualInexactTest__test_approx_equal_relative_ints():
    assertTrue(approx_equal(64, 47, tol=0, rel=0.36))
    assertTrue(approx_equal(64, 47, tol=0, rel=0.37))
    assertTrue(approx_equal(449, 512, tol=0, rel=0.125))
    assertTrue(approx_equal(448, 512, tol=0, rel=0.125))
    assertFalse(approx_equal(447, 512, tol=0, rel=0.125))

def ApproxEqualInexactTest__test_approx_equal_relative_floats():
    for x in [-178.34, -0.1, 0.1, 1.0, 36.97, 2847.136, 9145.074]:
        do_approx_equal_rel_test(x, 0.02)
        do_approx_equal_rel_test(x, 0.0001)

def ApproxEqualInexactTest__test_approx_equal_relative_fractions():
    F = Fraction
    delta = Fraction(3, 8)
    for f in [F(3, 84), F(17, 30), F(49, 50), F(92, 85)]:
        for d in (delta, float(delta)):
            do_approx_equal_rel_test(f, d)
            do_approx_equal_rel_test(-f, d)

def ApproxEqualInexactTest__test_approx_equal_relative_decimals():
    for d in map(Decimal, '0.02 1.0 5.7 13.67 94.138 91027.9321'.split()):
        do_approx_equal_rel_test(d, Decimal('0.001'))
        do_approx_equal_rel_test(-d, Decimal('0.05'))

def ApproxEqualInexactTest__test_approx_equal_both1():
    do_check_both(7.955, 7.952, 0.004, 0.00038, True, True)
    do_check_both(-7.387, -7.386, 0.002, 0.0002, True, True)

def ApproxEqualInexactTest__test_approx_equal_both2():
    do_check_both(7.955, 7.952, 0.004, 0.00037, True, False)

def ApproxEqualInexactTest__test_approx_equal_both3():
    do_check_both(7.955, 7.952, 0.001, 0.00038, False, True)

def ApproxEqualInexactTest__test_approx_equal_both4():
    do_check_both(2.78, 2.75, 0.01, 0.001, False, False)
    do_check_both(971.44, 971.47, 0.02, 3e-05, False, False)


# Test functions from ApproxEqualSpecialsTest
def ApproxEqualSpecialsTest__test_inf():
    for type_ in (float, Decimal):
        inf = type_('inf')
        assertTrue(approx_equal(inf, inf))
        assertTrue(approx_equal(inf, inf, 0, 0))
        assertTrue(approx_equal(inf, inf, 1, 0.01))
        assertTrue(approx_equal(-inf, -inf))
        assertFalse(approx_equal(inf, -inf))
        assertFalse(approx_equal(inf, 1000))

def ApproxEqualSpecialsTest__test_nan():
    for type_ in (float, Decimal):
        nan = type_('nan')
        for other in (nan, type_('inf'), 1000):
            assertFalse(approx_equal(nan, other))

def ApproxEqualSpecialsTest__test_float_zeroes():
    nzero = math.copysign(0.0, -1)
    assertTrue(approx_equal(nzero, 0.0, tol=0.1, rel=0.1))

def ApproxEqualSpecialsTest__test_decimal_zeroes():
    nzero = Decimal('-0.0')
    assertTrue(approx_equal(nzero, Decimal(0), tol=0.1, rel=0.1))


# Helper methods from TestNumericTestCase
def do_test(args):
    actual_msg = NumericTestCase._make_std_err_msg(*args)
    expected = generate_substrings(*args)
    for substring in expected:
        assertIn(substring, actual_msg)

def generate_substrings(first, second, tol, rel, idx):
    """Return substrings we expect to see in error messages."""
    abs_err, rel_err = _calc_errors(first, second)
    substrings = ['tol=%r' % tol, 'rel=%r' % rel, 'absolute error = %r' % abs_err, 'relative error = %r' % rel_err]
    if idx is not None:
        substrings.append('differ at index %d' % idx)
    return substrings

# Test functions from TestNumericTestCase
def TestNumericTestCase__test_numerictestcase_is_testcase():
    assertTrue(issubclass(NumericTestCase, unittest.TestCase))

def TestNumericTestCase__test_error_msg_numeric():
    args = (2.5, 4.0, 0.5, 0.25, None)
    do_test(args)

def TestNumericTestCase__test_error_msg_sequence():
    args = (3.75, 8.25, 1.25, 0.5, 7)
    do_test(args)


# Test functions from GlobalsTest
def GlobalsTest__test_meta():
    for meta in expected_metadata:
        assertTrue(hasattr(module, meta), '%s not present' % meta)

def GlobalsTest__test_check_all():
    for name in __all__:
        assertFalse(name.startswith('_'), 'private name "%s" in __all__' % name)
        assertTrue(hasattr(module, name), 'missing name "%s" in __all__' % name)


# Test functions from StatisticsErrorTest
def StatisticsErrorTest__test_has_exception():
    errmsg = 'Expected StatisticsError to be a ValueError, but got a subclass of %r instead.'
    assertTrue(hasattr(statistics, 'StatisticsError'))
    assertTrue(issubclass(StatisticsError, ValueError), errmsg % StatisticsError.__base__)


# Test functions from ExactRatioTest
def ExactRatioTest__test_int():
    for i in (-20, -3, 0, 5, 99, 10 ** 20):
        assertEqual(_exact_ratio(i), (i, 1))

def ExactRatioTest__test_fraction():
    numerators = (-5, 1, 12, 38)
    for n in numerators:
        f = Fraction(n, 37)
        assertEqual(_exact_ratio(f), (n, 37))

def ExactRatioTest__test_decimal():
    D = Decimal
    assertEqual(_exact_ratio(D('0.125')), (1, 8))
    assertEqual(_exact_ratio(D('12.345')), (2469, 200))
    assertEqual(_exact_ratio(D('-1.98')), (-99, 50))

def ExactRatioTest__test_inf():
    INF = float('INF')

    class MyFloat(float):
        pass

    class MyDecimal(Decimal):
        pass
    for inf in (INF, -INF):
        for type_ in (float, MyFloat, Decimal, MyDecimal):
            x = type_(inf)
            ratio = _exact_ratio(x)
            assertEqual(ratio, (x, None))
            assertEqual(type(ratio[0]), type_)
            assertTrue(math.isinf(ratio[0]))

def ExactRatioTest__test_float_nan():
    NAN = float('NAN')

    class MyFloat(float):
        pass
    for nan in (NAN, MyFloat(NAN)):
        ratio = _exact_ratio(nan)
        assertTrue(math.isnan(ratio[0]))
        assertIs(ratio[1], None)
        assertEqual(type(ratio[0]), type(nan))

def ExactRatioTest__test_decimal_nan():
    NAN = Decimal('NAN')
    sNAN = Decimal('sNAN')

    class MyDecimal(Decimal):
        pass
    for nan in (NAN, MyDecimal(NAN), sNAN, MyDecimal(sNAN)):
        ratio = _exact_ratio(nan)
        assertTrue(_nan_equal(ratio[0], nan))
        assertIs(ratio[1], None)
        assertEqual(type(ratio[0]), type(nan))


# Test functions from DecimalToRatioTest
def DecimalToRatioTest__test_infinity():
    inf = Decimal('INF')
    assertEqual(_exact_ratio(inf), (inf, None))
    assertEqual(_exact_ratio(-inf), (-inf, None))

def DecimalToRatioTest__test_nan():
    for nan in (Decimal('NAN'), Decimal('sNAN')):
        num, den = _exact_ratio(nan)
        assertTrue(_nan_equal(num, nan))
        assertIs(den, None)

def DecimalToRatioTest__test_sign():
    numbers = [Decimal('9.8765e12'), Decimal('9.8765e-12')]
    for d in numbers:
        assert d > 0
        num, den = _exact_ratio(d)
        assertGreaterEqual(num, 0)
        assertGreater(den, 0)
        num, den = _exact_ratio(-d)
        assertLessEqual(num, 0)
        assertGreater(den, 0)

def DecimalToRatioTest__test_negative_exponent():
    t = _exact_ratio(Decimal('0.1234'))
    assertEqual(t, (617, 5000))

def DecimalToRatioTest__test_positive_exponent():
    t = _exact_ratio(Decimal('1.234e7'))
    assertEqual(t, (12340000, 1))

def DecimalToRatioTest__test_regression_20536():
    t = _exact_ratio(Decimal('1e2'))
    assertEqual(t, (100, 1))
    t = _exact_ratio(Decimal('1.47e5'))
    assertEqual(t, (147000, 1))


# Test functions from IsFiniteTest
def IsFiniteTest__test_finite():
    for x in (5, Fraction(1, 3), 2.5, Decimal('5.5')):
        assertTrue(_isfinite(x))

def IsFiniteTest__test_infinity():
    for x in (float('inf'), Decimal('inf')):
        assertFalse(_isfinite(x))

def IsFiniteTest__test_nan():
    for x in (float('nan'), Decimal('NAN'), Decimal('sNAN')):
        assertFalse(_isfinite(x))


# Helper methods from CoerceTest
def assertCoerceTo(A, B):
    """Assert that type A coerces to B."""
    assertIs(_coerce(A, B), B)
    assertIs(_coerce(B, A), B)

def check_coerce_to(A, B):
    """Checks that type A coerces to B, including subclasses."""
    assertCoerceTo(A, B)

    class SubclassOfA(A):
        pass
    assertCoerceTo(SubclassOfA, B)

    class SubclassOfB(B):
        pass
    assertCoerceTo(A, SubclassOfB)
    assertCoerceTo(SubclassOfA, SubclassOfB)

def assertCoerceRaises(A, B):
    """Assert that coercing A to B, or vice versa, raises TypeError."""
    assertRaises(TypeError, _coerce, (A, B))
    assertRaises(TypeError, _coerce, (B, A))

def check_type_coercions(T):
    """Check that type T coerces correctly with subclasses of itself."""
    assert T is not bool
    assertIs(_coerce(T, T), T)

    class U(T):
        pass

    class V(T):
        pass

    class W(U):
        pass
    for typ in (U, V, W):
        assertCoerceTo(T, typ)
    assertCoerceTo(U, W)
    assertCoerceRaises(U, V)
    assertCoerceRaises(V, W)

# Test functions from CoerceTest
def CoerceTest__test_bool():
    for T in (int, float, Fraction, Decimal):
        assertIs(_coerce(T, bool), T)

        class MyClass(T):
            pass
        assertIs(_coerce(MyClass, bool), MyClass)

def CoerceTest__test_int():
    check_type_coercions(int)
    for typ in (float, Fraction, Decimal):
        check_coerce_to(int, typ)

def CoerceTest__test_fraction():
    check_type_coercions(Fraction)
    check_coerce_to(Fraction, float)

def CoerceTest__test_decimal():
    check_type_coercions(Decimal)

def CoerceTest__test_float():
    check_type_coercions(float)

def CoerceTest__test_non_numeric_types():
    for bad_type in (str, list, type(None), tuple, dict):
        for good_type in (int, float, Fraction, Decimal):
            assertCoerceRaises(good_type, bad_type)

def CoerceTest__test_incompatible_types():
    for T in (float, Fraction):

        class MySubclass(T):
            pass
        assertCoerceRaises(T, Decimal)
        assertCoerceRaises(MySubclass, Decimal)


# Helper methods from ConvertTest
def check_exact_equal(x, y):
    """Check that x equals y, and has the same type as well."""
    assertEqual(x, y)
    assertIs(type(x), type(y))

# Test functions from ConvertTest
def ConvertTest__test_int():
    x = _convert(Fraction(71), int)
    check_exact_equal(x, 71)

    class MyInt(int):
        pass
    x = _convert(Fraction(17), MyInt)
    check_exact_equal(x, MyInt(17))

def ConvertTest__test_fraction():
    x = _convert(Fraction(95, 99), Fraction)
    check_exact_equal(x, Fraction(95, 99))

    class MyFraction(Fraction):

        def __truediv__(self, other):
            return __class__(super().__truediv__(other))
    x = _convert(Fraction(71, 13), MyFraction)
    check_exact_equal(x, MyFraction(71, 13))

def ConvertTest__test_float():
    x = _convert(Fraction(-1, 2), float)
    check_exact_equal(x, -0.5)

    class MyFloat(float):

        def __truediv__(self, other):
            return __class__(super().__truediv__(other))
    x = _convert(Fraction(9, 8), MyFloat)
    check_exact_equal(x, MyFloat(1.125))

def ConvertTest__test_decimal():
    x = _convert(Fraction(1, 40), Decimal)
    check_exact_equal(x, Decimal('0.025'))

    class MyDecimal(Decimal):

        def __truediv__(self, other):
            return __class__(super().__truediv__(other))
    x = _convert(Fraction(-15, 16), MyDecimal)
    check_exact_equal(x, MyDecimal('-0.9375'))

def ConvertTest__test_inf():
    for INF in (float('inf'), Decimal('inf')):
        for inf in (INF, -INF):
            x = _convert(inf, type(inf))
            check_exact_equal(x, inf)

def ConvertTest__test_nan():
    for nan in (float('nan'), Decimal('NAN'), Decimal('sNAN')):
        x = _convert(nan, type(nan))
        assertTrue(_nan_equal(x, nan))


# Test functions from FailNegTest
def FailNegTest__test_pass_through():
    values = [1, 2.0, Fraction(3), Decimal(4)]
    new = list(_fail_neg(values))
    assertEqual(values, new)


# Helper methods from TestSum
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

# Test functions from TestSum
def TestSum__test_empty_data():
    func = _sum
    for data in ([], (), iter([])):
        assertEqual(func(data), (int, Fraction(0), 0))

def TestSum__test_ints():
    func = _sum
    assertEqual(func([1, 5, 3, -4, -8, 20, 42, 1]), (int, Fraction(60), 8))

def TestSum__test_floats():
    func = _sum
    assertEqual(func([0.25] * 20), (float, Fraction(5.0), 20))

def TestSum__test_fractions():
    func = _sum
    assertEqual(func([Fraction(1, 1000)] * 500), (Fraction, Fraction(1, 2), 500))

def TestSum__test_decimals():
    func = _sum
    D = Decimal
    data = [D('0.001'), D('5.246'), D('1.702'), D('-0.025'), D('3.974'), D('2.328'), D('4.617'), D('2.843')]
    assertEqual(func(data), (Decimal, Decimal('20.686'), 8))


# Helper methods from SumTortureTest
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

# Test functions from SumTortureTest
def SumTortureTest__test_torture():
    assertEqual(_sum([1, 1e+100, 1, -1e+100] * 10000), (float, Fraction(20000.0), 40000))
    assertEqual(_sum([1e+100, 1, 1, -1e+100] * 10000), (float, Fraction(20000.0), 40000))
    T, num, count = _sum([1e-100, 1, 1e-100, -1] * 10000)
    assertIs(T, float)
    assertEqual(count, 40000)
    assertApproxEqual(float(num), 2e-96, rel=5e-16)


# Helper methods from SumSpecialValues
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def check_infinity(x, inf):
    """Check x is an infinity of the same type and sign as inf."""
    assertTrue(math.isinf(x))
    assertIs(type(x), type(inf))
    assertEqual(x > 0, inf > 0)
    assert x == inf

def do_test_inf(inf):
    result = _sum([1, 2, inf, 3])[1]
    check_infinity(result, inf)
    result = _sum([1, 2, inf, 3, inf, 4])[1]
    check_infinity(result, inf)

# Test functions from SumSpecialValues
def SumSpecialValues__test_nan():
    for type_ in (float, Decimal):
        nan = type_('nan')
        result = _sum([1, nan, 2])[1]
        assertIs(type(result), type_)
        assertTrue(math.isnan(result))

def SumSpecialValues__test_float_inf():
    inf = float('inf')
    for sign in (+1, -1):
        do_test_inf(sign * inf)

def SumSpecialValues__test_decimal_inf():
    inf = Decimal('inf')
    for sign in (+1, -1):
        do_test_inf(sign * inf)

def SumSpecialValues__test_float_mismatched_infs():
    inf = float('inf')
    result = _sum([1, 2, inf, 3, -inf, 4])[1]
    assertTrue(math.isnan(result))

def SumSpecialValues__test_decimal_extendedcontext_mismatched_infs_to_nan():
    inf = Decimal('inf')
    data = [1, 2, inf, 3, -inf, 4]
    with decimal.localcontext(decimal.ExtendedContext):
        assertTrue(math.isnan(_sum(data)[1]))


# Helper methods from TestMean
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestMean
def TestMean__test_single_value():
    func = mean
    for x in (23, 42.5, 1300000000000000.0, Fraction(15, 19), Decimal('0.28')):
        assertEqual(func([x]), x)

def TestMean__test_types_conserved():
    func = mean
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)

def TestMean__test_torture_pep():
    func = mean
    assertEqual(func([1e+100, 1, 3, -1e+100]), 1)

def TestMean__test_inf():
    func = mean
    raw = [1, 3, 5, 7, 9]
    for kind in (float, Decimal):
        for sign in (1, -1):
            inf = kind('inf') * sign
            data = raw + [inf]
            result = func(data)
            assertTrue(math.isinf(result))
            assertEqual(result, inf)

def TestMean__test_mismatched_infs():
    func = mean
    data = [2, 4, 6, float('inf'), 1, 3, 5, float('-inf')]
    result = func(data)
    assertTrue(math.isnan(result))

def TestMean__test_nan():
    func = mean
    raw = [1, 3, 5, 7, 9]
    for kind in (float, Decimal):
        inf = kind('nan')
        data = raw + [inf]
        result = func(data)
        assertTrue(math.isnan(result))

def TestMean__test_big_data():
    func = mean
    c = 1000000000.0
    data = [3.4, 4.5, 4.9, 6.7, 6.8, 7.2, 8.0, 8.1, 9.4]
    expected = func(data) + c
    assert expected != c
    result = func([x + c for x in data])
    assertEqual(result, expected)

def TestMean__test_regression_20561():
    func = mean
    d = Decimal('1e4')
    assertEqual(mean([d]), d)

def TestMean__test_regression_25177():
    func = mean
    assertEqual(mean([8.988465674311579e+307, 8.98846567431158e+307]), 8.98846567431158e+307)
    big = 8.98846567431158e+307
    tiny = 5e-324
    for n in (2, 3, 5, 200):
        assertEqual(mean([big] * n), big)
        assertEqual(mean([tiny] * n), tiny)


# Helper methods from TestHarmonicMean
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestHarmonicMean
def TestHarmonicMean__test_single_value():
    func = harmonic_mean
    for x in (23, 42.5, 1300000000000000.0, Fraction(15, 19), Decimal('0.28')):
        assertEqual(func([x]), x)

def TestHarmonicMean__test_types_conserved():
    func = harmonic_mean
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)

def TestHarmonicMean__test_zero():
    func = harmonic_mean
    values = [1, 0, 2]
    assertEqual(func(values), 0)

def TestHarmonicMean__test_singleton_lists():
    func = harmonic_mean
    for x in range(1, 101):
        assertEqual(func([x]), x)

def TestHarmonicMean__test_inf():
    func = harmonic_mean
    values = [2.0, float('inf'), 1.0]
    assertEqual(func(values), 2.0)

def TestHarmonicMean__test_nan():
    func = harmonic_mean
    values = [2.0, float('nan'), 1.0]
    assertTrue(math.isnan(func(values)))

def TestHarmonicMean__test_multiply_data_points():
    func = harmonic_mean
    c = 111
    data = [3.4, 4.5, 4.9, 6.7, 6.8, 7.2, 8.0, 8.1, 9.4]
    expected = func(data) * c
    result = func([x * c for x in data])
    assertEqual(result, expected)


# Helper methods from TestMedian
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

# Test functions from TestMedian
def TestMedian__test_single_value():
    func = median
    for x in (23, 42.5, 1300000000000000.0, Fraction(15, 19), Decimal('0.28')):
        assertEqual(func([x]), x)

def TestMedian__test_even_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6]
    assert len(data) % 2 == 0
    assertEqual(func(data), 3.5)

def TestMedian__test_odd_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6, 9]
    assert len(data) % 2 == 1
    assertEqual(func(data), 4)


# Helper methods from TestMedianDataType
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

def prepare_data():
    data = list(range(15))
    assert len(data) % 2 == 1
    while data == sorted(data):
        random.shuffle(data)
    return data

# Test functions from TestMedianDataType
def TestMedianDataType__test_types_conserved():
    func = median
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)


# Helper methods from TestMedianLow
def prepare_data():
    """Overload method from UnivariateCommonMixin."""
    data = super().prepare_data()
    if len(data) % 2 != 1:
        data.append(2)
    return data

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestMedianLow
def TestMedianLow__test_even_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6]
    assert len(data) % 2 == 0
    assertEqual(func(data), 3.5)

def TestMedianLow__test_odd_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6, 9]
    assert len(data) % 2 == 1
    assertEqual(func(data), 4)

def TestMedianLow__test_types_conserved():
    func = median
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)


# Helper methods from TestMedianHigh
def prepare_data():
    """Overload method from UnivariateCommonMixin."""
    data = super().prepare_data()
    if len(data) % 2 != 1:
        data.append(2)
    return data

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestMedianHigh
def TestMedianHigh__test_even_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6]
    assert len(data) % 2 == 0
    assertEqual(func(data), 3.5)

def TestMedianHigh__test_odd_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6, 9]
    assert len(data) % 2 == 1
    assertEqual(func(data), 4)

def TestMedianHigh__test_types_conserved():
    func = median
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)


# Helper methods from TestMedianGrouped
def prepare_data():
    """Overload method from UnivariateCommonMixin."""
    data = super().prepare_data()
    if len(data) % 2 != 1:
        data.append(2)
    return data

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

# Test functions from TestMedianGrouped
def TestMedianGrouped__test_even_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6]
    assert len(data) % 2 == 0
    assertEqual(func(data), 3.5)

def TestMedianGrouped__test_odd_ints():
    func = median
    data = [1, 2, 3, 4, 5, 6, 9]
    assert len(data) % 2 == 1
    assertEqual(func(data), 4)

def TestMedianGrouped__test_single_value():
    func = median
    for x in (23, 42.5, 1300000000000000.0, Fraction(15, 19), Decimal('0.28')):
        assertEqual(func([x]), x)

def TestMedianGrouped__test_repeated_single_value():
    func = median
    for x in prepare_values_for_repeated_single_test():
        for count in (2, 5, 10, 20):
            with subTest(x=x, count=count):
                data = [x] * count
                assertEqual(func(data), x)

def TestMedianGrouped__test_odd_number_repeated():
    func = median
    data = [12, 13, 14, 14, 14, 15, 15]
    assert len(data) % 2 == 1
    assertEqual(func(data), 14)
    data = [12, 13, 14, 14, 14, 14, 15]
    assert len(data) % 2 == 1
    assertEqual(func(data), 13.875)
    data = [5, 10, 10, 15, 20, 20, 20, 20, 25, 25, 30]
    assert len(data) % 2 == 1
    assertEqual(func(data, 5), 19.375)
    data = [16, 18, 18, 18, 18, 20, 20, 20, 22, 22, 22, 24, 24, 26, 28]
    assert len(data) % 2 == 1
    assertApproxEqual(func(data, 2), 20.66666667, tol=1e-08)

def TestMedianGrouped__test_even_number_repeated():
    func = median
    data = [5, 10, 10, 15, 20, 20, 20, 25, 25, 30]
    assert len(data) % 2 == 0
    assertApproxEqual(func(data, 5), 19.16666667, tol=1e-08)
    data = [2, 3, 4, 4, 4, 5]
    assert len(data) % 2 == 0
    assertApproxEqual(func(data), 3.83333333, tol=1e-08)
    data = [2, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6]
    assert len(data) % 2 == 0
    assertEqual(func(data), 4.5)
    data = [3, 4, 4, 4, 5, 5, 5, 5, 6, 6]
    assert len(data) % 2 == 0
    assertEqual(func(data), 4.75)

def TestMedianGrouped__test_interval():
    func = median
    data = [2.25, 2.5, 2.5, 2.75, 2.75, 3.0, 3.0, 3.25, 3.5, 3.75]
    assertEqual(func(data, 0.25), 2.875)
    data = [2.25, 2.5, 2.5, 2.75, 2.75, 2.75, 3.0, 3.0, 3.25, 3.5, 3.75]
    assertApproxEqual(func(data, 0.25), 2.83333333, tol=1e-08)
    data = [220, 220, 240, 260, 260, 260, 260, 280, 280, 300, 320, 340]
    assertEqual(func(data, 20), 265.0)


# Helper methods from TestMode
def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_values_for_repeated_single_test():
    return (3.5, 17, 2500000000000000.0, Fraction(61, 67), Decimal('4.9712'))

def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestMode
def TestMode__test_single_value():
    func = mode
    for x in (23, 42.5, 1300000000000000.0, Fraction(15, 19), Decimal('0.28')):
        assertEqual(func([x]), x)

def TestMode__test_range_data():
    func = mode
    data = range(20, 50, 3)
    expected = func(list(data))
    assertEqual(func(data), expected)

def TestMode__test_types_conserved():
    func = mode
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)

def TestMode__test_nominal_data():
    func = mode
    data = 'abcbdb'
    assertEqual(func(data), 'b')
    data = 'fe fi fo fum fi fi'.split()
    assertEqual(func(data), 'fi')

def TestMode__test_bimodal_data():
    func = mode
    data = [1, 1, 2, 2, 2, 2, 3, 4, 5, 6, 6, 6, 6, 7, 8, 9, 9]
    assert data.count(2) == data.count(6) == 4
    assertEqual(func(data), 2)

def TestMode__test_unique_data():
    func = mode
    data = list(range(10))
    assertEqual(func(data), 0)

def TestMode__test_counter_data():
    func = mode
    c = collections.Counter(a=1, b=2)
    assertEqual(func(c), 'a')


# Test functions from TestMultiMode
def TestMultiMode__test_basics():
    assertEqual(multimode('aabbbbbbbbcc'), ['b'])
    assertEqual(multimode('aabbbbccddddeeffffgg'), ['b', 'd', 'f'])
    assertEqual(multimode(''), [])


# Test functions from TestFMean
def TestFMean__test_basics():
    D = Decimal
    F = Fraction
    for data, expected_mean, kind in [([3.5, 4.0, 5.25], 4.25, 'floats'), ([D('3.5'), D('4.0'), D('5.25')], 4.25, 'decimals'), ([F(7, 2), F(4, 1), F(21, 4)], 4.25, 'fractions'), ([True, False, True, True, False], 0.6, 'booleans'), ([3.5, 4, F(21, 4)], 4.25, 'mixed types'), ((3.5, 4.0, 5.25), 4.25, 'tuple'), (iter([3.5, 4.0, 5.25]), 4.25, 'iterator')]:
        actual_mean = fmean(data)
        assertIs(type(actual_mean), float, kind)
        assertEqual(actual_mean, expected_mean, kind)


# Helper methods from TestPVariance
def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestPVariance
def TestPVariance__test_single_value():
    func = pvariance
    for x in (11, 19.8, 460000000000000.0, Fraction(21, 34), Decimal('8.392')):
        assertEqual(func([x]), 0)

def TestPVariance__test_repeated_single_value():
    func = pvariance
    for x in (7.2, 49, 8100000000000000.0, Fraction(3, 7), Decimal('62.4802')):
        for count in (2, 3, 5, 15):
            data = [x] * count
            assertEqual(func(data), 0)

def TestPVariance__test_domain_error_regression():
    func = pvariance
    data = [0.123456789012345] * 10000
    result = func(data)
    assertApproxEqual(result, 0.0, tol=5e-17)
    assertGreaterEqual(result, 0)

def TestPVariance__test_shift_data():
    func = pvariance
    raw = [1.03, 1.27, 1.94, 2.04, 2.58, 3.14, 4.75, 4.98, 5.42, 6.78]
    expected = func(raw)
    shift = 100000.0
    data = [x + shift for x in raw]
    assertApproxEqual(func(data), expected)

def TestPVariance__test_shift_data_exact():
    func = pvariance
    raw = [1, 3, 3, 4, 5, 7, 9, 10, 11, 16]
    assert all((x == int(x) for x in raw))
    expected = func(raw)
    shift = 10 ** 9
    data = [x + shift for x in raw]
    assertEqual(func(data), expected)

def TestPVariance__test_types_conserved():
    func = pvariance
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)

def TestPVariance__test_ints():
    func = pvariance
    data = [4, 7, 13, 16]
    exact = 22.5
    assertEqual(func(data), exact)

def TestPVariance__test_fractions():
    func = pvariance
    F = Fraction
    data = [F(1, 4), F(1, 4), F(3, 4), F(7, 4)]
    exact = F(3, 8)
    result = func(data)
    assertEqual(result, exact)
    assertIsInstance(result, Fraction)

def TestPVariance__test_decimals():
    func = pvariance
    D = Decimal
    data = [D('12.1'), D('12.2'), D('12.5'), D('12.9')]
    exact = D('0.096875')
    result = func(data)
    assertEqual(result, exact)
    assertIsInstance(result, Decimal)

def TestPVariance__test_accuracy_bug_20499():
    func = pvariance
    data = [0, 0, 1]
    exact = 2 / 9
    result = func(data)
    assertEqual(result, exact)
    assertIsInstance(result, float)


# Helper methods from TestVariance
def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

def prepare_types_for_conservation_test():
    """Return the types which are expected to be conserved."""

    class MyFloat(float):

        def __truediv__(self, other):
            return type(self)(super().__truediv__(other))

        def __rtruediv__(self, other):
            return type(self)(super().__rtruediv__(other))

        def __sub__(self, other):
            return type(self)(super().__sub__(other))

        def __rsub__(self, other):
            return type(self)(super().__rsub__(other))

        def __pow__(self, other):
            return type(self)(super().__pow__(other))

        def __add__(self, other):
            return type(self)(super().__add__(other))
        __radd__ = __add__

        def __mul__(self, other):
            return type(self)(super().__mul__(other))
        __rmul__ = __mul__
    return (float, Decimal, Fraction, MyFloat)

# Test functions from TestVariance
def TestVariance__test_single_value():
    func = variance
    for x in (11, 19.8, 460000000000000.0, Fraction(21, 34), Decimal('8.392')):
        assertEqual(func([x]), 0)

def TestVariance__test_repeated_single_value():
    func = variance
    for x in (7.2, 49, 8100000000000000.0, Fraction(3, 7), Decimal('62.4802')):
        for count in (2, 3, 5, 15):
            data = [x] * count
            assertEqual(func(data), 0)

def TestVariance__test_domain_error_regression():
    func = variance
    data = [0.123456789012345] * 10000
    result = func(data)
    assertApproxEqual(result, 0.0, tol=5e-17)
    assertGreaterEqual(result, 0)

def TestVariance__test_shift_data():
    func = variance
    raw = [1.03, 1.27, 1.94, 2.04, 2.58, 3.14, 4.75, 4.98, 5.42, 6.78]
    expected = func(raw)
    shift = 100000.0
    data = [x + shift for x in raw]
    assertApproxEqual(func(data), expected)

def TestVariance__test_shift_data_exact():
    func = variance
    raw = [1, 3, 3, 4, 5, 7, 9, 10, 11, 16]
    assert all((x == int(x) for x in raw))
    expected = func(raw)
    shift = 10 ** 9
    data = [x + shift for x in raw]
    assertEqual(func(data), expected)

def TestVariance__test_types_conserved():
    func = variance
    data = prepare_data()
    for kind in prepare_types_for_conservation_test():
        d = [kind(x) for x in data]
        result = func(d)
        assertIs(type(result), kind)

def TestVariance__test_ints():
    func = variance
    data = [4, 7, 13, 16]
    exact = 30
    assertEqual(func(data), exact)

def TestVariance__test_fractions():
    func = variance
    F = Fraction
    data = [F(1, 4), F(1, 4), F(3, 4), F(7, 4)]
    exact = F(1, 2)
    result = func(data)
    assertEqual(result, exact)
    assertIsInstance(result, Fraction)

def TestVariance__test_decimals():
    func = variance
    D = Decimal
    data = [D(2), D(2), D(7), D(9)]
    exact = 4 * D('9.5') / D(3)
    result = func(data)
    assertEqual(result, exact)
    assertIsInstance(result, Decimal)

def TestVariance__test_center_not_at_mean():
    func = variance
    data = (1.0, 2.0)
    assertEqual(func(data), 0.5)
    assertEqual(func(data, xbar=2.0), 1.0)

def TestVariance__test_accuracy_bug_20499():
    func = variance
    data = [0, 0, 2]
    exact = 4 / 3
    result = func(data)
    assertEqual(result, exact)
    assertIsInstance(result, float)


# Helper methods from TestPStdev
def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

# Test functions from TestPStdev
def TestPStdev__test_single_value():
    func = pstdev
    for x in (11, 19.8, 460000000000000.0, Fraction(21, 34), Decimal('8.392')):
        assertEqual(func([x]), 0)

def TestPStdev__test_repeated_single_value():
    func = pstdev
    for x in (7.2, 49, 8100000000000000.0, Fraction(3, 7), Decimal('62.4802')):
        for count in (2, 3, 5, 15):
            data = [x] * count
            assertEqual(func(data), 0)

def TestPStdev__test_domain_error_regression():
    func = pstdev
    data = [0.123456789012345] * 10000
    result = func(data)
    assertApproxEqual(result, 0.0, tol=5e-17)
    assertGreaterEqual(result, 0)

def TestPStdev__test_shift_data():
    func = pstdev
    raw = [1.03, 1.27, 1.94, 2.04, 2.58, 3.14, 4.75, 4.98, 5.42, 6.78]
    expected = func(raw)
    shift = 100000.0
    data = [x + shift for x in raw]
    assertApproxEqual(func(data), expected)

def TestPStdev__test_shift_data_exact():
    func = pstdev
    raw = [1, 3, 3, 4, 5, 7, 9, 10, 11, 16]
    assert all((x == int(x) for x in raw))
    expected = func(raw)
    shift = 10 ** 9
    data = [x + shift for x in raw]
    assertEqual(func(data), expected)

def TestPStdev__test_center_not_at_mean():
    func = pstdev
    data = (3, 6, 7, 10)
    assertEqual(func(data), 2.5)
    assertEqual(func(data, mu=0.5), 6.5)


# Test functions from TestSqrtHelpers
def TestSqrtHelpers__test_integer_sqrt_of_frac_rto():
    for n, m in itertools.product(range(100), range(1, 1000)):
        r = _integer_sqrt_of_frac_rto(n, m)
        assertIsInstance(r, int)
        if r * r * m == n:
            continue
        assertEqual(r & 1, 1)
        assertTrue(m * (r - 1) ** 2 < n < m * (r + 1) ** 2)


# Helper methods from TestStdev
def prepare_data():
    """Return int data for various tests."""
    data = list(range(10))
    while data == sorted(data):
        random.shuffle(data)
    return data

def check_for_type_error(*args):
    assertRaises(TypeError, func, *args)

def assertApproxEqual(first, second, tol=None, rel=None, msg=None):
    """Test passes if ``first`` and ``second`` are approximately equal.

        This test passes if ``first`` and ``second`` are equal to
        within ``tol``, an absolute error, or ``rel``, a relative error.

        If either ``tol`` or ``rel`` are None or not given, they default to
        test attributes of the same name (by default, 0).

        The objects may be either numbers, or sequences of numbers. Sequences
        are tested element-by-element.

        >>> class MyTest(NumericTestCase):
        ...     def test_number(self):
        ...         x = 1.0/6
        ...         y = sum([x]*6)
        ...         self.assertApproxEqual(y, 1.0, tol=1e-15)
        ...     def test_sequence(self):
        ...         a = [1.001, 1.001e-10, 1.001e10]
        ...         b = [1.0, 1e-10, 1e10]
        ...         self.assertApproxEqual(a, b, rel=1e-3)
        ...
        >>> import unittest
        >>> from io import StringIO  # Suppress test runner output.
        >>> suite = unittest.TestLoader().loadTestsFromTestCase(MyTest)
        >>> unittest.TextTestRunner(stream=StringIO()).run(suite)
        <unittest.runner.TextTestResult run=2 errors=0 failures=0>

        """
    if tol is None:
        pass
    if rel is None:
        pass
    if isinstance(first, collections.abc.Sequence) and isinstance(second, collections.abc.Sequence):
        check = _check_approx_seq
    else:
        check = _check_approx_num
    check(first, second, tol, rel, msg)

def _check_approx_seq(first, second, tol, rel, msg):
    if len(first) != len(second):
        standardMsg = 'sequences differ in length: %d items != %d items' % (len(first), len(second))
        msg = _formatMessage(msg, standardMsg)
        raise failureException(msg)
    for i, (a, e) in enumerate(zip(first, second)):
        _check_approx_num(a, e, tol, rel, msg, i)

def _check_approx_num(first, second, tol, rel, msg, idx=None):
    if approx_equal(first, second, tol, rel):
        return None
    standardMsg = _make_std_err_msg(first, second, tol, rel, idx)
    msg = _formatMessage(msg, standardMsg)
    raise failureException(msg)

def _make_std_err_msg(first, second, tol, rel, idx):
    assert first != second
    template = '  %r != %r\n  values differ by more than tol=%r and rel=%r\n  -> absolute error = %r\n  -> relative error = %r'
    if idx is not None:
        header = 'numeric sequences first differ at index %d.\n' % idx
        template = header + template
    abs_err, rel_err = _calc_errors(first, second)
    return template % (first, second, tol, rel, abs_err, rel_err)

# Test functions from TestStdev
def TestStdev__test_single_value():
    func = stdev
    for x in (11, 19.8, 460000000000000.0, Fraction(21, 34), Decimal('8.392')):
        assertEqual(func([x]), 0)

def TestStdev__test_repeated_single_value():
    func = stdev
    for x in (7.2, 49, 8100000000000000.0, Fraction(3, 7), Decimal('62.4802')):
        for count in (2, 3, 5, 15):
            data = [x] * count
            assertEqual(func(data), 0)

def TestStdev__test_domain_error_regression():
    func = stdev
    data = [0.123456789012345] * 10000
    result = func(data)
    assertApproxEqual(result, 0.0, tol=5e-17)
    assertGreaterEqual(result, 0)

def TestStdev__test_shift_data():
    func = stdev
    raw = [1.03, 1.27, 1.94, 2.04, 2.58, 3.14, 4.75, 4.98, 5.42, 6.78]
    expected = func(raw)
    shift = 100000.0
    data = [x + shift for x in raw]
    assertApproxEqual(func(data), expected)

def TestStdev__test_shift_data_exact():
    func = stdev
    raw = [1, 3, 3, 4, 5, 7, 9, 10, 11, 16]
    assert all((x == int(x) for x in raw))
    expected = func(raw)
    shift = 10 ** 9
    data = [x + shift for x in raw]
    assertEqual(func(data), expected)

def TestStdev__test_center_not_at_mean():
    func = stdev
    data = (1.0, 2.0)
    assertEqual(func(data, xbar=2.0), 1.0)


# Test functions from TestGeometricMean
def TestGeometricMean__test_various_input_types():
    D = Decimal
    F = Fraction
    expected_mean = 4.18886
    for data, kind in [([3.5, 4.0, 5.25], 'floats'), ([D('3.5'), D('4.0'), D('5.25')], 'decimals'), ([F(7, 2), F(4, 1), F(21, 4)], 'fractions'), ([3.5, 4, F(21, 4)], 'mixed types'), ((3.5, 4.0, 5.25), 'tuple'), (iter([3.5, 4.0, 5.25]), 'iterator')]:
        actual_mean = geometric_mean(data)
        assertIs(type(actual_mean), float, kind)
        assertAlmostEqual(actual_mean, expected_mean, places=5)

def TestGeometricMean__test_big_and_small():
    large = 2.0 ** 1000
    big_gm = geometric_mean([54.0 * large, 24.0 * large, 36.0 * large])
    assertTrue(math.isclose(big_gm, 36.0 * large))
    assertFalse(math.isinf(big_gm))
    small = 2.0 ** (-1000)
    small_gm = geometric_mean([54.0 * small, 24.0 * small, 36.0 * small])
    assertTrue(math.isclose(small_gm, 36.0 * small))
    assertNotEqual(small_gm, 0.0)


# Test functions from TestQuantiles
def TestQuantiles__test_equal_inputs():
    for n in range(2, 10):
        data = [10.0] * n
        assertEqual(quantiles(data), [10.0, 10.0, 10.0])
        assertEqual(quantiles(data, method='inclusive'), [10.0, 10.0, 10.0])


# Test functions from TestCorrelationAndCovariance
def TestCorrelationAndCovariance__test_results():
    for x, y, result in [([1, 2, 3], [1, 2, 3], 1), ([1, 2, 3], [-1, -2, -3], -1), ([1, 2, 3], [3, 2, 1], -1), ([1, 2, 3], [1, 2, 1], 0), ([1, 2, 3], [1, 3, 2], 0.5)]:
        assertAlmostEqual(correlation(x, y), result)
        assertAlmostEqual(covariance(x, y), result)

def TestCorrelationAndCovariance__test_different_scales():
    x = [1, 2, 3]
    y = [10, 30, 20]
    assertAlmostEqual(correlation(x, y), 0.5)
    assertAlmostEqual(covariance(x, y), 5)
    y = [0.1, 0.2, 0.3]
    assertAlmostEqual(correlation(x, y), 1)
    assertAlmostEqual(covariance(x, y), 0.1)


# ======================================================================
# Direct invocation
# ======================================================================

try:
    TestModules__test_py_functions()
    print("TestModules.test_py_functions: PASS")
except Exception as _e:
    print("TestModules.test_py_functions: FAIL -", _e)
try:
    ApproxEqualSymmetryTest__test_relative_symmetry()
    print("ApproxEqualSymmetryTest.test_relative_symmetry: PASS")
except Exception as _e:
    print("ApproxEqualSymmetryTest.test_relative_symmetry: FAIL -", _e)
try:
    ApproxEqualSymmetryTest__test_symmetry()
    print("ApproxEqualSymmetryTest.test_symmetry: PASS")
except Exception as _e:
    print("ApproxEqualSymmetryTest.test_symmetry: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_ints()
    print("ApproxEqualExactTest.test_exactly_equal_ints: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_ints: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_floats()
    print("ApproxEqualExactTest.test_exactly_equal_floats: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_floats: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_fractions()
    print("ApproxEqualExactTest.test_exactly_equal_fractions: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_fractions: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_decimals()
    print("ApproxEqualExactTest.test_exactly_equal_decimals: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_decimals: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_absolute()
    print("ApproxEqualExactTest.test_exactly_equal_absolute: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_absolute: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_absolute_decimals()
    print("ApproxEqualExactTest.test_exactly_equal_absolute_decimals: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_absolute_decimals: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_relative()
    print("ApproxEqualExactTest.test_exactly_equal_relative: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_relative: FAIL -", _e)
try:
    ApproxEqualExactTest__test_exactly_equal_both()
    print("ApproxEqualExactTest.test_exactly_equal_both: PASS")
except Exception as _e:
    print("ApproxEqualExactTest.test_exactly_equal_both: FAIL -", _e)
try:
    ApproxEqualUnequalTest__test_exactly_unequal_ints()
    print("ApproxEqualUnequalTest.test_exactly_unequal_ints: PASS")
except Exception as _e:
    print("ApproxEqualUnequalTest.test_exactly_unequal_ints: FAIL -", _e)
try:
    ApproxEqualUnequalTest__test_exactly_unequal_floats()
    print("ApproxEqualUnequalTest.test_exactly_unequal_floats: PASS")
except Exception as _e:
    print("ApproxEqualUnequalTest.test_exactly_unequal_floats: FAIL -", _e)
try:
    ApproxEqualUnequalTest__test_exactly_unequal_fractions()
    print("ApproxEqualUnequalTest.test_exactly_unequal_fractions: PASS")
except Exception as _e:
    print("ApproxEqualUnequalTest.test_exactly_unequal_fractions: FAIL -", _e)
try:
    ApproxEqualUnequalTest__test_exactly_unequal_decimals()
    print("ApproxEqualUnequalTest.test_exactly_unequal_decimals: PASS")
except Exception as _e:
    print("ApproxEqualUnequalTest.test_exactly_unequal_decimals: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_absolute_ints()
    print("ApproxEqualInexactTest.test_approx_equal_absolute_ints: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_absolute_ints: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_absolute_floats()
    print("ApproxEqualInexactTest.test_approx_equal_absolute_floats: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_absolute_floats: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_absolute_fractions()
    print("ApproxEqualInexactTest.test_approx_equal_absolute_fractions: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_absolute_fractions: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_absolute_decimals()
    print("ApproxEqualInexactTest.test_approx_equal_absolute_decimals: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_absolute_decimals: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_cross_zero()
    print("ApproxEqualInexactTest.test_cross_zero: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_cross_zero: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_relative_ints()
    print("ApproxEqualInexactTest.test_approx_equal_relative_ints: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_relative_ints: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_relative_floats()
    print("ApproxEqualInexactTest.test_approx_equal_relative_floats: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_relative_floats: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_relative_fractions()
    print("ApproxEqualInexactTest.test_approx_equal_relative_fractions: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_relative_fractions: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_relative_decimals()
    print("ApproxEqualInexactTest.test_approx_equal_relative_decimals: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_relative_decimals: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_both1()
    print("ApproxEqualInexactTest.test_approx_equal_both1: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_both1: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_both2()
    print("ApproxEqualInexactTest.test_approx_equal_both2: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_both2: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_both3()
    print("ApproxEqualInexactTest.test_approx_equal_both3: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_both3: FAIL -", _e)
try:
    ApproxEqualInexactTest__test_approx_equal_both4()
    print("ApproxEqualInexactTest.test_approx_equal_both4: PASS")
except Exception as _e:
    print("ApproxEqualInexactTest.test_approx_equal_both4: FAIL -", _e)
try:
    ApproxEqualSpecialsTest__test_inf()
    print("ApproxEqualSpecialsTest.test_inf: PASS")
except Exception as _e:
    print("ApproxEqualSpecialsTest.test_inf: FAIL -", _e)
try:
    ApproxEqualSpecialsTest__test_nan()
    print("ApproxEqualSpecialsTest.test_nan: PASS")
except Exception as _e:
    print("ApproxEqualSpecialsTest.test_nan: FAIL -", _e)
try:
    ApproxEqualSpecialsTest__test_float_zeroes()
    print("ApproxEqualSpecialsTest.test_float_zeroes: PASS")
except Exception as _e:
    print("ApproxEqualSpecialsTest.test_float_zeroes: FAIL -", _e)
try:
    ApproxEqualSpecialsTest__test_decimal_zeroes()
    print("ApproxEqualSpecialsTest.test_decimal_zeroes: PASS")
except Exception as _e:
    print("ApproxEqualSpecialsTest.test_decimal_zeroes: FAIL -", _e)
try:
    TestNumericTestCase__test_numerictestcase_is_testcase()
    print("TestNumericTestCase.test_numerictestcase_is_testcase: PASS")
except Exception as _e:
    print("TestNumericTestCase.test_numerictestcase_is_testcase: FAIL -", _e)
try:
    TestNumericTestCase__test_error_msg_numeric()
    print("TestNumericTestCase.test_error_msg_numeric: PASS")
except Exception as _e:
    print("TestNumericTestCase.test_error_msg_numeric: FAIL -", _e)
try:
    TestNumericTestCase__test_error_msg_sequence()
    print("TestNumericTestCase.test_error_msg_sequence: PASS")
except Exception as _e:
    print("TestNumericTestCase.test_error_msg_sequence: FAIL -", _e)
try:
    GlobalsTest__test_meta()
    print("GlobalsTest.test_meta: PASS")
except Exception as _e:
    print("GlobalsTest.test_meta: FAIL -", _e)
try:
    GlobalsTest__test_check_all()
    print("GlobalsTest.test_check_all: PASS")
except Exception as _e:
    print("GlobalsTest.test_check_all: FAIL -", _e)
try:
    StatisticsErrorTest__test_has_exception()
    print("StatisticsErrorTest.test_has_exception: PASS")
except Exception as _e:
    print("StatisticsErrorTest.test_has_exception: FAIL -", _e)
try:
    ExactRatioTest__test_int()
    print("ExactRatioTest.test_int: PASS")
except Exception as _e:
    print("ExactRatioTest.test_int: FAIL -", _e)
try:
    ExactRatioTest__test_fraction()
    print("ExactRatioTest.test_fraction: PASS")
except Exception as _e:
    print("ExactRatioTest.test_fraction: FAIL -", _e)
try:
    ExactRatioTest__test_decimal()
    print("ExactRatioTest.test_decimal: PASS")
except Exception as _e:
    print("ExactRatioTest.test_decimal: FAIL -", _e)
try:
    ExactRatioTest__test_inf()
    print("ExactRatioTest.test_inf: PASS")
except Exception as _e:
    print("ExactRatioTest.test_inf: FAIL -", _e)
try:
    ExactRatioTest__test_float_nan()
    print("ExactRatioTest.test_float_nan: PASS")
except Exception as _e:
    print("ExactRatioTest.test_float_nan: FAIL -", _e)
try:
    ExactRatioTest__test_decimal_nan()
    print("ExactRatioTest.test_decimal_nan: PASS")
except Exception as _e:
    print("ExactRatioTest.test_decimal_nan: FAIL -", _e)
try:
    DecimalToRatioTest__test_infinity()
    print("DecimalToRatioTest.test_infinity: PASS")
except Exception as _e:
    print("DecimalToRatioTest.test_infinity: FAIL -", _e)
try:
    DecimalToRatioTest__test_nan()
    print("DecimalToRatioTest.test_nan: PASS")
except Exception as _e:
    print("DecimalToRatioTest.test_nan: FAIL -", _e)
try:
    DecimalToRatioTest__test_sign()
    print("DecimalToRatioTest.test_sign: PASS")
except Exception as _e:
    print("DecimalToRatioTest.test_sign: FAIL -", _e)
try:
    DecimalToRatioTest__test_negative_exponent()
    print("DecimalToRatioTest.test_negative_exponent: PASS")
except Exception as _e:
    print("DecimalToRatioTest.test_negative_exponent: FAIL -", _e)
try:
    DecimalToRatioTest__test_positive_exponent()
    print("DecimalToRatioTest.test_positive_exponent: PASS")
except Exception as _e:
    print("DecimalToRatioTest.test_positive_exponent: FAIL -", _e)
try:
    DecimalToRatioTest__test_regression_20536()
    print("DecimalToRatioTest.test_regression_20536: PASS")
except Exception as _e:
    print("DecimalToRatioTest.test_regression_20536: FAIL -", _e)
try:
    IsFiniteTest__test_finite()
    print("IsFiniteTest.test_finite: PASS")
except Exception as _e:
    print("IsFiniteTest.test_finite: FAIL -", _e)
try:
    IsFiniteTest__test_infinity()
    print("IsFiniteTest.test_infinity: PASS")
except Exception as _e:
    print("IsFiniteTest.test_infinity: FAIL -", _e)
try:
    IsFiniteTest__test_nan()
    print("IsFiniteTest.test_nan: PASS")
except Exception as _e:
    print("IsFiniteTest.test_nan: FAIL -", _e)
try:
    CoerceTest__test_bool()
    print("CoerceTest.test_bool: PASS")
except Exception as _e:
    print("CoerceTest.test_bool: FAIL -", _e)
try:
    CoerceTest__test_int()
    print("CoerceTest.test_int: PASS")
except Exception as _e:
    print("CoerceTest.test_int: FAIL -", _e)
try:
    CoerceTest__test_fraction()
    print("CoerceTest.test_fraction: PASS")
except Exception as _e:
    print("CoerceTest.test_fraction: FAIL -", _e)
try:
    CoerceTest__test_decimal()
    print("CoerceTest.test_decimal: PASS")
except Exception as _e:
    print("CoerceTest.test_decimal: FAIL -", _e)
try:
    CoerceTest__test_float()
    print("CoerceTest.test_float: PASS")
except Exception as _e:
    print("CoerceTest.test_float: FAIL -", _e)
try:
    CoerceTest__test_non_numeric_types()
    print("CoerceTest.test_non_numeric_types: PASS")
except Exception as _e:
    print("CoerceTest.test_non_numeric_types: FAIL -", _e)
try:
    CoerceTest__test_incompatible_types()
    print("CoerceTest.test_incompatible_types: PASS")
except Exception as _e:
    print("CoerceTest.test_incompatible_types: FAIL -", _e)
try:
    ConvertTest__test_int()
    print("ConvertTest.test_int: PASS")
except Exception as _e:
    print("ConvertTest.test_int: FAIL -", _e)
try:
    ConvertTest__test_fraction()
    print("ConvertTest.test_fraction: PASS")
except Exception as _e:
    print("ConvertTest.test_fraction: FAIL -", _e)
try:
    ConvertTest__test_float()
    print("ConvertTest.test_float: PASS")
except Exception as _e:
    print("ConvertTest.test_float: FAIL -", _e)
try:
    ConvertTest__test_decimal()
    print("ConvertTest.test_decimal: PASS")
except Exception as _e:
    print("ConvertTest.test_decimal: FAIL -", _e)
try:
    ConvertTest__test_inf()
    print("ConvertTest.test_inf: PASS")
except Exception as _e:
    print("ConvertTest.test_inf: FAIL -", _e)
try:
    ConvertTest__test_nan()
    print("ConvertTest.test_nan: PASS")
except Exception as _e:
    print("ConvertTest.test_nan: FAIL -", _e)
try:
    FailNegTest__test_pass_through()
    print("FailNegTest.test_pass_through: PASS")
except Exception as _e:
    print("FailNegTest.test_pass_through: FAIL -", _e)
try:
    TestSum__test_empty_data()
    print("TestSum.test_empty_data: PASS")
except Exception as _e:
    print("TestSum.test_empty_data: FAIL -", _e)
try:
    TestSum__test_ints()
    print("TestSum.test_ints: PASS")
except Exception as _e:
    print("TestSum.test_ints: FAIL -", _e)
try:
    TestSum__test_floats()
    print("TestSum.test_floats: PASS")
except Exception as _e:
    print("TestSum.test_floats: FAIL -", _e)
try:
    TestSum__test_fractions()
    print("TestSum.test_fractions: PASS")
except Exception as _e:
    print("TestSum.test_fractions: FAIL -", _e)
try:
    TestSum__test_decimals()
    print("TestSum.test_decimals: PASS")
except Exception as _e:
    print("TestSum.test_decimals: FAIL -", _e)
try:
    SumTortureTest__test_torture()
    print("SumTortureTest.test_torture: PASS")
except Exception as _e:
    print("SumTortureTest.test_torture: FAIL -", _e)
try:
    SumSpecialValues__test_nan()
    print("SumSpecialValues.test_nan: PASS")
except Exception as _e:
    print("SumSpecialValues.test_nan: FAIL -", _e)
try:
    SumSpecialValues__test_float_inf()
    print("SumSpecialValues.test_float_inf: PASS")
except Exception as _e:
    print("SumSpecialValues.test_float_inf: FAIL -", _e)
try:
    SumSpecialValues__test_decimal_inf()
    print("SumSpecialValues.test_decimal_inf: PASS")
except Exception as _e:
    print("SumSpecialValues.test_decimal_inf: FAIL -", _e)
try:
    SumSpecialValues__test_float_mismatched_infs()
    print("SumSpecialValues.test_float_mismatched_infs: PASS")
except Exception as _e:
    print("SumSpecialValues.test_float_mismatched_infs: FAIL -", _e)
try:
    SumSpecialValues__test_decimal_extendedcontext_mismatched_infs_to_nan()
    print("SumSpecialValues.test_decimal_extendedcontext_mismatched_infs_to_nan: PASS")
except Exception as _e:
    print("SumSpecialValues.test_decimal_extendedcontext_mismatched_infs_to_nan: FAIL -", _e)
try:
    TestMean__test_single_value()
    print("TestMean.test_single_value: PASS")
except Exception as _e:
    print("TestMean.test_single_value: FAIL -", _e)
try:
    TestMean__test_types_conserved()
    print("TestMean.test_types_conserved: PASS")
except Exception as _e:
    print("TestMean.test_types_conserved: FAIL -", _e)
try:
    TestMean__test_torture_pep()
    print("TestMean.test_torture_pep: PASS")
except Exception as _e:
    print("TestMean.test_torture_pep: FAIL -", _e)
try:
    TestMean__test_inf()
    print("TestMean.test_inf: PASS")
except Exception as _e:
    print("TestMean.test_inf: FAIL -", _e)
try:
    TestMean__test_mismatched_infs()
    print("TestMean.test_mismatched_infs: PASS")
except Exception as _e:
    print("TestMean.test_mismatched_infs: FAIL -", _e)
try:
    TestMean__test_nan()
    print("TestMean.test_nan: PASS")
except Exception as _e:
    print("TestMean.test_nan: FAIL -", _e)
try:
    TestMean__test_big_data()
    print("TestMean.test_big_data: PASS")
except Exception as _e:
    print("TestMean.test_big_data: FAIL -", _e)
try:
    TestMean__test_regression_20561()
    print("TestMean.test_regression_20561: PASS")
except Exception as _e:
    print("TestMean.test_regression_20561: FAIL -", _e)
try:
    TestMean__test_regression_25177()
    print("TestMean.test_regression_25177: PASS")
except Exception as _e:
    print("TestMean.test_regression_25177: FAIL -", _e)
try:
    TestHarmonicMean__test_single_value()
    print("TestHarmonicMean.test_single_value: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_single_value: FAIL -", _e)
try:
    TestHarmonicMean__test_types_conserved()
    print("TestHarmonicMean.test_types_conserved: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_types_conserved: FAIL -", _e)
try:
    TestHarmonicMean__test_zero()
    print("TestHarmonicMean.test_zero: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_zero: FAIL -", _e)
try:
    TestHarmonicMean__test_singleton_lists()
    print("TestHarmonicMean.test_singleton_lists: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_singleton_lists: FAIL -", _e)
try:
    TestHarmonicMean__test_inf()
    print("TestHarmonicMean.test_inf: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_inf: FAIL -", _e)
try:
    TestHarmonicMean__test_nan()
    print("TestHarmonicMean.test_nan: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_nan: FAIL -", _e)
try:
    TestHarmonicMean__test_multiply_data_points()
    print("TestHarmonicMean.test_multiply_data_points: PASS")
except Exception as _e:
    print("TestHarmonicMean.test_multiply_data_points: FAIL -", _e)
try:
    TestMedian__test_single_value()
    print("TestMedian.test_single_value: PASS")
except Exception as _e:
    print("TestMedian.test_single_value: FAIL -", _e)
try:
    TestMedian__test_even_ints()
    print("TestMedian.test_even_ints: PASS")
except Exception as _e:
    print("TestMedian.test_even_ints: FAIL -", _e)
try:
    TestMedian__test_odd_ints()
    print("TestMedian.test_odd_ints: PASS")
except Exception as _e:
    print("TestMedian.test_odd_ints: FAIL -", _e)
try:
    TestMedianDataType__test_types_conserved()
    print("TestMedianDataType.test_types_conserved: PASS")
except Exception as _e:
    print("TestMedianDataType.test_types_conserved: FAIL -", _e)
try:
    TestMedianLow__test_even_ints()
    print("TestMedianLow.test_even_ints: PASS")
except Exception as _e:
    print("TestMedianLow.test_even_ints: FAIL -", _e)
try:
    TestMedianLow__test_odd_ints()
    print("TestMedianLow.test_odd_ints: PASS")
except Exception as _e:
    print("TestMedianLow.test_odd_ints: FAIL -", _e)
try:
    TestMedianLow__test_types_conserved()
    print("TestMedianLow.test_types_conserved: PASS")
except Exception as _e:
    print("TestMedianLow.test_types_conserved: FAIL -", _e)
try:
    TestMedianHigh__test_even_ints()
    print("TestMedianHigh.test_even_ints: PASS")
except Exception as _e:
    print("TestMedianHigh.test_even_ints: FAIL -", _e)
try:
    TestMedianHigh__test_odd_ints()
    print("TestMedianHigh.test_odd_ints: PASS")
except Exception as _e:
    print("TestMedianHigh.test_odd_ints: FAIL -", _e)
try:
    TestMedianHigh__test_types_conserved()
    print("TestMedianHigh.test_types_conserved: PASS")
except Exception as _e:
    print("TestMedianHigh.test_types_conserved: FAIL -", _e)
try:
    TestMedianGrouped__test_even_ints()
    print("TestMedianGrouped.test_even_ints: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_even_ints: FAIL -", _e)
try:
    TestMedianGrouped__test_odd_ints()
    print("TestMedianGrouped.test_odd_ints: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_odd_ints: FAIL -", _e)
try:
    TestMedianGrouped__test_odd_number_repeated()
    print("TestMedianGrouped.test_odd_number_repeated: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_odd_number_repeated: FAIL -", _e)
try:
    TestMedianGrouped__test_even_number_repeated()
    print("TestMedianGrouped.test_even_number_repeated: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_even_number_repeated: FAIL -", _e)
try:
    TestMedianGrouped__test_repeated_single_value()
    print("TestMedianGrouped.test_repeated_single_value: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_repeated_single_value: FAIL -", _e)
try:
    TestMedianGrouped__test_single_value()
    print("TestMedianGrouped.test_single_value: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_single_value: FAIL -", _e)
try:
    TestMedianGrouped__test_interval()
    print("TestMedianGrouped.test_interval: PASS")
except Exception as _e:
    print("TestMedianGrouped.test_interval: FAIL -", _e)
try:
    TestMode__test_single_value()
    print("TestMode.test_single_value: PASS")
except Exception as _e:
    print("TestMode.test_single_value: FAIL -", _e)
try:
    TestMode__test_types_conserved()
    print("TestMode.test_types_conserved: PASS")
except Exception as _e:
    print("TestMode.test_types_conserved: FAIL -", _e)
try:
    TestMode__test_range_data()
    print("TestMode.test_range_data: PASS")
except Exception as _e:
    print("TestMode.test_range_data: FAIL -", _e)
try:
    TestMode__test_nominal_data()
    print("TestMode.test_nominal_data: PASS")
except Exception as _e:
    print("TestMode.test_nominal_data: FAIL -", _e)
try:
    TestMode__test_bimodal_data()
    print("TestMode.test_bimodal_data: PASS")
except Exception as _e:
    print("TestMode.test_bimodal_data: FAIL -", _e)
try:
    TestMode__test_unique_data()
    print("TestMode.test_unique_data: PASS")
except Exception as _e:
    print("TestMode.test_unique_data: FAIL -", _e)
try:
    TestMode__test_counter_data()
    print("TestMode.test_counter_data: PASS")
except Exception as _e:
    print("TestMode.test_counter_data: FAIL -", _e)
try:
    TestMultiMode__test_basics()
    print("TestMultiMode.test_basics: PASS")
except Exception as _e:
    print("TestMultiMode.test_basics: FAIL -", _e)
try:
    TestFMean__test_basics()
    print("TestFMean.test_basics: PASS")
except Exception as _e:
    print("TestFMean.test_basics: FAIL -", _e)
try:
    TestPVariance__test_single_value()
    print("TestPVariance.test_single_value: PASS")
except Exception as _e:
    print("TestPVariance.test_single_value: FAIL -", _e)
try:
    TestPVariance__test_repeated_single_value()
    print("TestPVariance.test_repeated_single_value: PASS")
except Exception as _e:
    print("TestPVariance.test_repeated_single_value: FAIL -", _e)
try:
    TestPVariance__test_domain_error_regression()
    print("TestPVariance.test_domain_error_regression: PASS")
except Exception as _e:
    print("TestPVariance.test_domain_error_regression: FAIL -", _e)
try:
    TestPVariance__test_shift_data()
    print("TestPVariance.test_shift_data: PASS")
except Exception as _e:
    print("TestPVariance.test_shift_data: FAIL -", _e)
try:
    TestPVariance__test_shift_data_exact()
    print("TestPVariance.test_shift_data_exact: PASS")
except Exception as _e:
    print("TestPVariance.test_shift_data_exact: FAIL -", _e)
try:
    TestPVariance__test_types_conserved()
    print("TestPVariance.test_types_conserved: PASS")
except Exception as _e:
    print("TestPVariance.test_types_conserved: FAIL -", _e)
try:
    TestPVariance__test_ints()
    print("TestPVariance.test_ints: PASS")
except Exception as _e:
    print("TestPVariance.test_ints: FAIL -", _e)
try:
    TestPVariance__test_fractions()
    print("TestPVariance.test_fractions: PASS")
except Exception as _e:
    print("TestPVariance.test_fractions: FAIL -", _e)
try:
    TestPVariance__test_decimals()
    print("TestPVariance.test_decimals: PASS")
except Exception as _e:
    print("TestPVariance.test_decimals: FAIL -", _e)
try:
    TestPVariance__test_accuracy_bug_20499()
    print("TestPVariance.test_accuracy_bug_20499: PASS")
except Exception as _e:
    print("TestPVariance.test_accuracy_bug_20499: FAIL -", _e)
try:
    TestVariance__test_single_value()
    print("TestVariance.test_single_value: PASS")
except Exception as _e:
    print("TestVariance.test_single_value: FAIL -", _e)
try:
    TestVariance__test_repeated_single_value()
    print("TestVariance.test_repeated_single_value: PASS")
except Exception as _e:
    print("TestVariance.test_repeated_single_value: FAIL -", _e)
try:
    TestVariance__test_domain_error_regression()
    print("TestVariance.test_domain_error_regression: PASS")
except Exception as _e:
    print("TestVariance.test_domain_error_regression: FAIL -", _e)
try:
    TestVariance__test_shift_data()
    print("TestVariance.test_shift_data: PASS")
except Exception as _e:
    print("TestVariance.test_shift_data: FAIL -", _e)
try:
    TestVariance__test_shift_data_exact()
    print("TestVariance.test_shift_data_exact: PASS")
except Exception as _e:
    print("TestVariance.test_shift_data_exact: FAIL -", _e)
try:
    TestVariance__test_types_conserved()
    print("TestVariance.test_types_conserved: PASS")
except Exception as _e:
    print("TestVariance.test_types_conserved: FAIL -", _e)
try:
    TestVariance__test_ints()
    print("TestVariance.test_ints: PASS")
except Exception as _e:
    print("TestVariance.test_ints: FAIL -", _e)
try:
    TestVariance__test_fractions()
    print("TestVariance.test_fractions: PASS")
except Exception as _e:
    print("TestVariance.test_fractions: FAIL -", _e)
try:
    TestVariance__test_decimals()
    print("TestVariance.test_decimals: PASS")
except Exception as _e:
    print("TestVariance.test_decimals: FAIL -", _e)
try:
    TestVariance__test_center_not_at_mean()
    print("TestVariance.test_center_not_at_mean: PASS")
except Exception as _e:
    print("TestVariance.test_center_not_at_mean: FAIL -", _e)
try:
    TestVariance__test_accuracy_bug_20499()
    print("TestVariance.test_accuracy_bug_20499: PASS")
except Exception as _e:
    print("TestVariance.test_accuracy_bug_20499: FAIL -", _e)
try:
    TestPStdev__test_single_value()
    print("TestPStdev.test_single_value: PASS")
except Exception as _e:
    print("TestPStdev.test_single_value: FAIL -", _e)
try:
    TestPStdev__test_repeated_single_value()
    print("TestPStdev.test_repeated_single_value: PASS")
except Exception as _e:
    print("TestPStdev.test_repeated_single_value: FAIL -", _e)
try:
    TestPStdev__test_domain_error_regression()
    print("TestPStdev.test_domain_error_regression: PASS")
except Exception as _e:
    print("TestPStdev.test_domain_error_regression: FAIL -", _e)
try:
    TestPStdev__test_shift_data()
    print("TestPStdev.test_shift_data: PASS")
except Exception as _e:
    print("TestPStdev.test_shift_data: FAIL -", _e)
try:
    TestPStdev__test_shift_data_exact()
    print("TestPStdev.test_shift_data_exact: PASS")
except Exception as _e:
    print("TestPStdev.test_shift_data_exact: FAIL -", _e)
try:
    TestPStdev__test_center_not_at_mean()
    print("TestPStdev.test_center_not_at_mean: PASS")
except Exception as _e:
    print("TestPStdev.test_center_not_at_mean: FAIL -", _e)
try:
    TestSqrtHelpers__test_integer_sqrt_of_frac_rto()
    print("TestSqrtHelpers.test_integer_sqrt_of_frac_rto: PASS")
except Exception as _e:
    print("TestSqrtHelpers.test_integer_sqrt_of_frac_rto: FAIL -", _e)
try:
    TestStdev__test_single_value()
    print("TestStdev.test_single_value: PASS")
except Exception as _e:
    print("TestStdev.test_single_value: FAIL -", _e)
try:
    TestStdev__test_repeated_single_value()
    print("TestStdev.test_repeated_single_value: PASS")
except Exception as _e:
    print("TestStdev.test_repeated_single_value: FAIL -", _e)
try:
    TestStdev__test_domain_error_regression()
    print("TestStdev.test_domain_error_regression: PASS")
except Exception as _e:
    print("TestStdev.test_domain_error_regression: FAIL -", _e)
try:
    TestStdev__test_shift_data()
    print("TestStdev.test_shift_data: PASS")
except Exception as _e:
    print("TestStdev.test_shift_data: FAIL -", _e)
try:
    TestStdev__test_shift_data_exact()
    print("TestStdev.test_shift_data_exact: PASS")
except Exception as _e:
    print("TestStdev.test_shift_data_exact: FAIL -", _e)
try:
    TestStdev__test_center_not_at_mean()
    print("TestStdev.test_center_not_at_mean: PASS")
except Exception as _e:
    print("TestStdev.test_center_not_at_mean: FAIL -", _e)
try:
    TestGeometricMean__test_various_input_types()
    print("TestGeometricMean.test_various_input_types: PASS")
except Exception as _e:
    print("TestGeometricMean.test_various_input_types: FAIL -", _e)
try:
    TestGeometricMean__test_big_and_small()
    print("TestGeometricMean.test_big_and_small: PASS")
except Exception as _e:
    print("TestGeometricMean.test_big_and_small: FAIL -", _e)
try:
    TestQuantiles__test_equal_inputs()
    print("TestQuantiles.test_equal_inputs: PASS")
except Exception as _e:
    print("TestQuantiles.test_equal_inputs: FAIL -", _e)
try:
    TestCorrelationAndCovariance__test_results()
    print("TestCorrelationAndCovariance.test_results: PASS")
except Exception as _e:
    print("TestCorrelationAndCovariance.test_results: FAIL -", _e)
try:
    TestCorrelationAndCovariance__test_different_scales()
    print("TestCorrelationAndCovariance.test_different_scales: PASS")
except Exception as _e:
    print("TestCorrelationAndCovariance.test_different_scales: FAIL -", _e)