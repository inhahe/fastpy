# Test: for loop over list inside generator
def items(lst):
    for x in lst:
        yield x

g = items([10, 20, 30])
print(next(g))
print(next(g))
print(next(g))
