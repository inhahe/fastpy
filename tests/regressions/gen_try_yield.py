# Regression: yields inside try/except blocks in generators
# Before fix:
# 1. Multiple sequential yields in try/except only produced the first value
#    because all yields got the same next_state in _gen_yields_to_returns.
# 2. For-loop with yield inside try produced nothing because the for→while
#    conversion result was discarded (original AST appended instead).
# 3. else clause yields were unreachable because yield→return in try body
#    exits without triggering the else clause.
# Fix: _gen_preprocess_body now flattens try/except with yields:
#   - Sequential yields: split body at yield boundaries, each piece gets
#     its own try/except wrapper.
#   - While-loop inside try: extract while as top-level, wrap non-yield
#     statements in try/except, keep yield statements bare.
#   - else clause: emitted as standalone statements after the try pieces.

# 1. Multiple sequential yields in try/except
def multi():
    try:
        yield 1
        yield 2
        yield 3
    except Exception:
        pass

assert list(multi()) == [1, 2, 3]

# 2. For-loop (range) inside try
def range_in_try(n):
    try:
        for i in range(n):
            yield i
    except Exception:
        pass

assert list(range_in_try(4)) == [0, 1, 2, 3]
assert list(range_in_try(0)) == []

# 3. For-loop (iterable) inside try
def iter_in_try(items):
    try:
        for x in items:
            yield x * 2
    except Exception:
        pass

assert list(iter_in_try([1, 2, 3])) == [2, 4, 6]
assert list(iter_in_try([])) == []

# 4. try/except/else with yields
def with_else():
    try:
        yield 1
        yield 2
    except Exception:
        yield 99
    else:
        yield 3

assert list(with_else()) == [1, 2, 3]

# 5. Nested try with yields
def nested_try():
    try:
        yield 1
        try:
            yield 2
        except:
            pass
        yield 3
    except:
        pass

assert list(nested_try()) == [1, 2, 3]

# 6. yield after try (should still work)
def after_try():
    try:
        yield 1
    except Exception:
        pass
    yield 2
    yield 3

assert list(after_try()) == [1, 2, 3]

# 7. while True with break inside try
def while_in_try():
    i = 0
    try:
        while True:
            if i >= 3:
                break
            yield i
            i += 1
    except Exception:
        pass

assert list(while_in_try()) == [0, 1, 2]

# 8. Single yield in try (no splitting needed)
def single_in_try():
    try:
        yield 42
    except Exception:
        pass

assert list(single_in_try()) == [42]

# 9. Code between yields in try
def code_between():
    try:
        x = 10
        yield x
        x = x + 5
        yield x
        x = x * 2
        yield x
    except Exception:
        pass

assert list(code_between()) == [10, 15, 30]

print("ok")
