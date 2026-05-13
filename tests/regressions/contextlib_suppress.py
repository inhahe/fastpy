# Regression: contextlib.suppress context manager
from contextlib import suppress

# Test 1: suppress specified exception
with suppress(ValueError):
    raise ValueError("suppressed")
print("after suppress 1")

# Test 2: don't suppress non-matching exception
try:
    with suppress(TypeError):
        raise ValueError("not suppressed")
except ValueError:
    print("caught ValueError")

# Test 3: suppress multiple exception types
with suppress(ValueError, TypeError, KeyError):
    raise KeyError("suppressed key error")
print("after suppress 3")

# Test 4: no exception
with suppress(ValueError):
    print("no exception")
print("done")
