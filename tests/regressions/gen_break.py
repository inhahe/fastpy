# Test: break inside while-True generator
# Regression: `break` in generator's while-True loop exited the
# state machine dispatch loop without marking the generator as
# finished, causing callers (list(), for-loop) to hang.

def limited(n):
    i = 0
    while True:
        if i >= n:
            break
        yield i
        i += 1

assert list(limited(3)) == [0, 1, 2]
assert list(limited(1)) == [0]
assert list(limited(0)) == []

# Break after yield
def take(gen, n):
    i = 0
    while True:
        yield next(gen)
        i += 1
        if i >= n:
            break

import sys
def counter():
    n = 0
    while True:
        yield n
        n += 1

assert list(take(counter(), 4)) == [0, 1, 2, 3]

print("ok")
