# Bug 1: yield in nested for-loop (inner iterates outer variable)
def flatten():
    data = [[1, 2], [3, 4]]
    for sub in data:
        for x in sub:
            yield x
print(list(flatten()))

# Bug 2: yield from inside for-loop
def flatten2():
    data = [[10, 20], [30, 40]]
    for sub in data:
        yield from sub
print(list(flatten2()))

# yield from with range-based for-loop
def pairs():
    for i in range(3):
        yield from [i * 10, i * 10 + 1]
print(list(pairs()))

# Nested yield with computation
def doubled():
    for row in [[1, 2], [3, 4]]:
        for val in row:
            yield val * 2
print(list(doubled()))
