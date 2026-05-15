# Regression: f-string format spec with FpyValue variable
# Previously crashed when a variable from tuple unpacking (FpyValue)
# was used with a float format spec like .2f — the pointer value
# was passed to format_spec_str instead of format_spec_float.

# Float from dict items unpacking
prices = {'apple': 1.50, 'banana': 0.75, 'cherry': 2.00}
for item, price in sorted(prices.items()):
    print(f"{item}: ${price:.2f}")

# Float from tuple unpacking
data = [('x', 3.14159), ('y', 2.71828)]
for name, val in data:
    print(f"{name} = {val:.3f}")

# Int from dict items unpacking with int spec
counts = {'a': 42, 'b': 7, 'c': 100}
for key, count in sorted(counts.items()):
    print(f"{key}: {count:>5d}")
