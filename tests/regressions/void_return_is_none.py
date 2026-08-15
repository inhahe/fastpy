# Regression: a function or method whose body never executes `return <expr>`
# compiles to a *void* LLVM function, and every call site substitutes the
# placeholder `i64 0`.  That placeholder carries no type information, so the
# result read back as the integer 0 instead of None — `print(f())` said "0",
# `f() is None` said False, and a variable assigned from such a call was typed
# INT.
#
# The fix keeps the placeholder (it is still an i64) and corrects only the
# *tag*: _call_is_void() answers "this call's Python value is None", and the
# tag-producing sites (print wrapping, FpyValue boxing, `is` comparison,
# variable type inference) emit NONE instead of falling back to the
# placeholder's own LLVM type.


def no_return():
    x = 1


def bare_pass():
    pass


def conditional_side_effect(n):
    if n > 0:
        print(f"positive {n}")


print(no_return())
print(bare_pass())
print(conditional_side_effect(1))
print(conditional_side_effect(-1))

# `is None` must agree with the printed value — it used to disagree, which is
# the shape of bug that survives a print-only test.
print(no_return() is None)
print(no_return() is not None)
print(bare_pass() is None)

# Through a variable, too: the assignment's inferred type is what decides how
# the value is later printed and compared.
r = no_return()
print(r)
print(r is None)
print(r is not None)

s = bare_pass()
print(s, s is None)


class Counter:
    def __init__(self):
        self.n = 0

    def bump(self):
        self.n = self.n + 1

    def reset(self):
        pass


c = Counter()
# Called for its value in every position that used to lose the tag...
print(c.bump())
print(c.reset())
print(c.bump() is None)
print(Counter().bump())
t = c.reset()
print(t)
print(t is None)
# ...and the side effect must still have happened exactly once per call.
print(c.n)

# A method that DOES return a value must be unaffected — the fix must not make
# every method look like it returns None.
class Answer:
    def get(self):
        return 42

    def label(self):
        return "answer"


a = Answer()
print(a.get())
print(a.get() is None)
print(a.label())
print(a.label() is None)


# Same for a plain function with a real return, including one that returns None
# explicitly on some paths (that one is NOT void — it has a `return <expr>`).
def maybe(n):
    if n > 0:
        return n
    return None


print(maybe(3), maybe(3) is None)
print(maybe(-1), maybe(-1) is None)

print("done")
