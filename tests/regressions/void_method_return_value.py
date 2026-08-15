# Regression: a method with no `return <expr>` is compiled to a void LLVM
# function, but the runtime's string dispatcher (fastpy_obj_call_methodN) used
# to call every method through an int64_t-returning pointer type — so the
# "return value" was whatever the callee left in the return register.
#
# The `with` statement is where that became data loss rather than noise: a
# truthy __exit__ result means "suppress the exception", so an exception raised
# in the body vanished instead of reaching its handler. It reproduced only when
# __exit__ did enough work to leave a non-zero value behind (touching `self` was
# enough), which made it look like a self-reference bug.
#
# The dispatchers now honour FpyMethodDef.returns_value.


class Tracker:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, a, b, c):
        # Touching self is what used to leave a non-zero return register.
        print(f"exit {self.name}")


class Suppressor:
    def __enter__(self):
        return self

    def __exit__(self, a, b, c):
        print("suppressing")
        return True


class Silent:
    """__exit__ that does nothing at all — the case that accidentally worked."""

    def __enter__(self):
        return self

    def __exit__(self, a, b, c):
        pass


# A None-returning __exit__ must NOT swallow the exception.
try:
    with Tracker("a"):
        raise ValueError("oops")
except ValueError as e:
    print(f"caught: {e}")

# ...even nested, and even when the inner manager also returns None.
try:
    with Tracker("outer"):
        with Tracker("inner"):
            raise KeyError("k")
except KeyError:
    print("caught nested")

# A trivial __exit__ must behave the same way.
try:
    with Silent():
        raise TypeError("t")
except TypeError:
    print("caught silent")

# A truthy __exit__ must still suppress — the fix must not break the other
# direction.
with Suppressor():
    raise RuntimeError("swallowed")
print("after suppressor")

# A void method called for its side effect must still run exactly once and be
# safe to call in expression position.  (Its *value* is still 0 rather than
# None — see the BUG-VOID-RETURNS-ZERO-NOT-NONE entry in known-issues.md, a
# separate and much wider gap that affects plain functions too, so this test
# deliberately does not print it.)
class Counter:
    def __init__(self):
        self.n = 0

    def bump(self):
        self.n = self.n + 1


c = Counter()
c.bump()
c.bump()
print(c.n)

print("done")
