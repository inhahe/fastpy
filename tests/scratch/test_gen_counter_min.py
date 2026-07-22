# Minimal: while True generator
def counter():
    n = 0
    while True:
        yield n
        n += 1

g = counter()
print(next(g))
print(next(g))
