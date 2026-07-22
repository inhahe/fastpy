# Test: conditional yield inside for-loop in generator
# Regression: when yield is inside `if cond:` within a for-loop,
# the loop counter must still increment on iterations where the
# condition is false (i.e., the yield doesn't execute).

# Filter pattern: yield only even numbers
def evens(n):
    for i in range(n):
        if i % 2 == 0:
            yield i

assert list(evens(6)) == [0, 2, 4]
assert list(evens(1)) == [0]
assert list(evens(0)) == []

# Squares pattern: yield every value
def squares(n):
    for i in range(n):
        yield i * i

assert list(squares(5)) == [0, 1, 4, 9, 16]
assert sum(squares(5)) == 30

# Mixed: conditional yield with post-yield code
def annotated_evens(n):
    count = 0
    for i in range(n):
        if i % 2 == 0:
            yield i
            count += 1
    # After loop, count should equal how many values we yielded

g = annotated_evens(6)
assert next(g) == 0
assert next(g) == 2
assert next(g) == 4

print("ok")
