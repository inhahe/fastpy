# Regression: contextmanager handles exceptions from with-body
from contextlib import contextmanager

@contextmanager
def suppress_value_error():
    try:
        yield
    except ValueError:
        print("caught ValueError")

@contextmanager
def log_and_suppress():
    try:
        yield "resource"
    except Exception as e:
        print(f"suppressed: {e}")

@contextmanager
def no_suppress():
    try:
        yield
    except TypeError:
        print("caught TypeError")

# Test 1: contextmanager catches the exception → suppressed
try:
    with suppress_value_error():
        raise ValueError("boom")
    print("after with 1")
except ValueError:
    print("NOT suppressed 1")

# Test 2: contextmanager catches with as-binding
try:
    with log_and_suppress() as res:
        print(f"got {res}")
        raise RuntimeError("oops")
    print("after with 2")
except RuntimeError:
    print("NOT suppressed 2")

# Test 3: contextmanager doesn't match the exception type → not suppressed
try:
    with no_suppress():
        raise ValueError("wrong type")
    print("after with 3")
except ValueError:
    print("propagated 3")

# Test 4: no exception → normal flow
with suppress_value_error():
    print("normal body")
print("done")
