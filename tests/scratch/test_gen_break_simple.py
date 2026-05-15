# Test: generator with early break (no yield before break)
def gen():
    i = 0
    while True:
        yield i
        i += 1
        if i >= 3:
            break

print(list(gen()))
