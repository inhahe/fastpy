def median(data):
    n = len(data)
    if n == 0:
        raise ValueError('no median for empty data')
    s = sorted(data)
    if n % 2 == 1:
        return s[n // 2]
    else:
        i = n // 2
        return (s[i - 1] + s[i]) / 2.0

print(median([1, 3, 5]))
print(median([1, 3, 5, 7]))
