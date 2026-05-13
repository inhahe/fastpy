# Bug 10: contextlib.contextmanager doesn't work
from contextlib import contextmanager

@contextmanager
def ctx(name):
    print("enter", name)
    yield name
    print("exit", name)

with ctx("test") as val:
    print("inside", val)
