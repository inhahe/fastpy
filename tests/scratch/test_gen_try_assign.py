# Test: variable assigned inside try block in generator
def safe_divide(values, divisor):
    for v in values:
        try:
            result = v / divisor
            yield result
        except ZeroDivisionError:
            yield 0

print(list(safe_divide([10, 20, 30], 5)))
