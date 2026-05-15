# Test: fibonacci generator
def fibonacci():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b

g = fibonacci()
result = []
for _ in range(10):
    result.append(next(g))
print(result)
