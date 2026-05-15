def g():
    yield from [1, 2, 3]
print(list(g()))
