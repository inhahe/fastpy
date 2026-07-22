# Regression: sorted() with key=lambda inside a function operating on
# list-of-tuples parameter. Tests that CSA correctly propagates the
# "list:tuple" element type so the lambda parameter is typed as LIST
# (pointer) rather than INT (scalar).

def sort_by_second(pairs):
    return sorted(pairs, key=lambda x: x[1])

data = [(1, 3), (2, 1), (3, 2)]
print(sort_by_second(data))

# Also test module-level sorted with key
data2 = [("Bob", 25), ("Alice", 30), ("Charlie", 20)]
print(sorted(data2, key=lambda x: x[0]))
print(sorted(data2, key=lambda x: x[1]))
