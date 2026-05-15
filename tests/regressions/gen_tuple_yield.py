# Test: generator yielding tuples and compound expressions
# Regression: tuple/list literals yielded from generators were
# mistagged as STR (the default pointer tag), causing them to
# print as empty/garbage strings instead of their actual content.

# Simple tuple yield — check string representation
def pairs():
    yield (1, 2)
    yield (3, 4)

g = pairs()
t1 = next(g)
t2 = next(g)
assert str(t1) == "(1, 2)", f"got {t1!r}"
assert str(t2) == "(3, 4)", f"got {t2!r}"

# Enumerate-like pattern: tuple with counter + string char
def indexed_chars(s):
    i = 0
    for c in s:
        yield (i, c)
        i += 1

result = list(indexed_chars("abc"))
assert str(result) == "[(0, 'a'), (1, 'b'), (2, 'c')]", f"got {result!r}"

# List yield from generator
def list_gen():
    yield [1, 2, 3]
    yield [4, 5]

g = list_gen()
a = next(g)
b = next(g)
assert str(a) == "[1, 2, 3]", f"got {a!r}"
assert str(b) == "[4, 5]", f"got {b!r}"

print("ok")
