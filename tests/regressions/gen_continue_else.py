# Regression: `continue` and `for-else` in generator for-loops
#
# Bug 1 (continue): In range-based for→while conversion, the index
# increment was placed AFTER the body.  A `continue` would skip the
# increment, causing an infinite loop on the same index.
# Fix: Move increment BEFORE the body so `continue` naturally works.
#
# Bug 2 (for-else): The for→while conversion dropped the `else`
# clause entirely.  In CPython, `for...else` runs the else body
# when the loop finishes without `break`.
# Fix: Append the preprocessed else clause after the while-loop.

# 1. continue in range-based generator
def odd_only():
    for i in range(6):
        if i % 2 == 0:
            continue
        yield i

assert list(odd_only()) == [1, 3, 5]

# 2. continue with multiple conditions
def skip_some():
    for i in range(10):
        if i < 3:
            continue
        if i > 6:
            continue
        yield i

assert list(skip_some()) == [3, 4, 5, 6]

# 3. continue with post-yield code
def with_accum():
    total = 0
    for i in range(5):
        if i == 2:
            continue
        total = total + i
        yield total

assert list(with_accum()) == [0, 1, 4, 8]

# 4. for-else (no break)
def with_else():
    for i in range(3):
        yield i
    else:
        yield 99

assert list(with_else()) == [0, 1, 2, 99]

# 5. for-else with break (else should NOT run)
def with_break():
    for i in range(5):
        yield i
        if i == 2:
            break
    else:
        yield 99

assert list(with_break()) == [0, 1, 2]

# 6. for-else on iter-based loop
def iter_else(items):
    for x in items:
        yield x
    else:
        yield -1

assert list(iter_else([10, 20])) == [10, 20, -1]
assert list(iter_else([])) == [-1]

# 7. continue in iter-based loop
def iter_continue(items):
    for x in items:
        if x < 0:
            continue
        yield x

assert list(iter_continue([1, -2, 3, -4, 5])) == [1, 3, 5]

print("ok")
