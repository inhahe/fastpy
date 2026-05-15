# Test: integer yield inside generator loop
def nums(n):
    i = 0
    while i < n:
        yield i
        i = i + 1

g = nums(3)
print(next(g))
print(next(g))
print(next(g))
