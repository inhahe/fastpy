# Test: for loop over range inside generator
def nums(n):
    for i in range(n):
        yield i

g = nums(3)
print(next(g))
print(next(g))
print(next(g))
