# Adapted from CPython Lib/test/test_statistics.py
# Tests basic statistics algorithms (pure Python)

def mean(data):
    if len(data) == 0:
        return 0.0
    total = 0.0
    for x in data:
        total += x
    return total / len(data)

def variance(data):
    if len(data) < 2:
        return 0.0
    m = mean(data)
    total = 0.0
    for x in data:
        diff = x - m
        total += diff * diff
    return total / (len(data) - 1)

def stdev(data):
    return variance(data) ** 0.5

def median(data):
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return float(sorted_data[n // 2])
    else:
        mid = n // 2
        return (sorted_data[mid - 1] + sorted_data[mid]) / 2.0

def mode(data):
    """Return the most common value."""
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

# Test mean
print(mean([1, 2, 3, 4, 5]))
print(mean([10, 20, 30]))
print(mean([1]))
print(mean([0, 0, 0, 0]))
print(round(mean([1.5, 2.5, 3.5]), 4))

# Test median
print(median([1, 2, 3, 4, 5]))
print(median([1, 2, 3, 4]))
print(median([5, 1, 3]))
print(median([1]))
print(median([7, 3]))

# Test variance
print(round(variance([1, 2, 3, 4, 5]), 4))
print(round(variance([10, 10, 10, 10]), 4))
print(round(variance([2, 4, 4, 4, 5, 5, 7, 9]), 4))

# Test stdev
print(round(stdev([1, 2, 3, 4, 5]), 4))
print(round(stdev([2, 4, 4, 4, 5, 5, 7, 9]), 4))

# Test mode
print(mode([1, 2, 2, 3, 3, 3, 4]))
print(mode([1, 1, 1, 2, 2, 3]))
print(mode([5]))

# More complex data sets
data1 = [4, 8, 15, 16, 23, 42]
print(round(mean(data1), 4))
print(median(data1))
print(round(variance(data1), 4))
print(round(stdev(data1), 4))

# Uniform data
uniform = list(range(1, 11))
print(mean(uniform))
print(median(uniform))
print(round(variance(uniform), 4))

# Data with negative numbers
negatives = [-5, -3, -1, 0, 1, 3, 5]
print(mean(negatives))
print(median(negatives))
print(round(variance(negatives), 4))

# Large data set
large = list(range(100))
print(mean(large))
print(median(large))

# Sorted vs unsorted (should give same results)
unsorted = [9, 1, 5, 3, 7, 2, 8, 4, 6, 0]
print(mean(unsorted))
print(median(unsorted))
print(round(variance(unsorted), 4))
