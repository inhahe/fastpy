# Regression: `return` in generators crashed the compiled binary.
# Before fix: bare `return` in generator function was compiled as a
# regular function return from the send() method, returning None
# instead of raising StopIteration.  This caused the caller to
# interpret None as a yielded value, leading to crashes.
# Fix: _gen_preprocess_body transforms `return` into
#   self._finished = True; raise StopIteration

# 1. Early return before any yield
def gen_early(n):
    if n <= 0:
        return
    yield n

assert list(gen_early(0)) == []
assert list(gen_early(1)) == [1]

# 2. Return after yield
def gen_after():
    yield 1
    return

assert list(gen_after()) == [1]

# 3. Conditional return
def gen_cond(n):
    yield n
    if n == 1:
        return
    yield n * 2

assert list(gen_cond(1)) == [1]
assert list(gen_cond(3)) == [3, 6]

# 4. Multiple return paths
def gen_multi(n):
    if n <= 0:
        return
    yield n
    if n == 1:
        return
    yield n * 2

assert list(gen_multi(0)) == []
assert list(gen_multi(1)) == [1]
assert list(gen_multi(3)) == [3, 6]

# 5. Return inside while True
def take(n):
    i = 0
    while True:
        if i >= n:
            return
        yield i
        i += 1

assert list(take(3)) == [0, 1, 2]
assert list(take(0)) == []

# 6. Return after unreachable yield
def gen_dead():
    yield 1
    yield 2
    return
    yield 3  # dead code

assert list(gen_dead()) == [1, 2]

print("ok")
