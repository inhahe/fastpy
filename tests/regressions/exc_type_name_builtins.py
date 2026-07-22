# Regression: type(e).__name__ works for all builtin exception types
# (both explicitly raised and runtime-raised)

# Runtime-raised ZeroDivisionError
try:
    x = 1 / 0
except ZeroDivisionError as e:
    print(type(e).__name__)

# Runtime-raised KeyError
try:
    d = {}
    v = d["missing"]
except KeyError as e:
    print(type(e).__name__)

# Runtime-raised IndexError
try:
    lst = [1, 2, 3]
    v = lst[10]
except IndexError as e:
    print(type(e).__name__)

# Explicitly raised ValueError
try:
    raise ValueError("bad value")
except ValueError as e:
    print(type(e).__name__)

# Explicitly raised TypeError
try:
    raise TypeError("wrong type")
except TypeError as e:
    print(type(e).__name__)

# Bare raise (no parens) — builtin
try:
    raise RuntimeError
except RuntimeError as e:
    print(type(e).__name__)

# Catch-all via Exception base class
try:
    raise ValueError("caught by parent")
except Exception as e:
    print(type(e).__name__)

# Bare re-raise preserves class name
try:
    try:
        raise ValueError("inner")
    except ValueError as e:
        raise
except ValueError as e:
    print(type(e).__name__)
