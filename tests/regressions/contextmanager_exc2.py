# Regression: contextmanager exception handling — edge cases
from contextlib import contextmanager

# Test 1: nested context managers with exception
@contextmanager
def outer():
    print("outer enter")
    try:
        yield "outer"
    except ValueError:
        print("outer caught ValueError")
    print("outer cleanup")

@contextmanager
def inner():
    print("inner enter")
    yield "inner"
    print("inner cleanup")

with outer() as o:
    with inner() as i:
        print(f"body: {o}, {i}")
        raise ValueError("nested")
print("after nested")

# Test 2: exception type mismatch — propagates
@contextmanager
def catches_type():
    try:
        yield
    except TypeError:
        print("caught TypeError")

try:
    with catches_type():
        raise ValueError("wrong")
except ValueError as e:
    print(f"propagated: {e}")

# Test 3: contextmanager with cleanup after except
@contextmanager
def cleanup_after():
    print("setup")
    try:
        yield
    except RuntimeError:
        print("handled RuntimeError")
    finally:
        print("final cleanup")

with cleanup_after():
    raise RuntimeError("test")
print("done")
