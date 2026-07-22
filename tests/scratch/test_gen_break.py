# Test: generator with break
def limited(n):
    i = 0
    while True:
        if i >= n:
            break
        yield i
        i += 1

print(list(limited(3)))
