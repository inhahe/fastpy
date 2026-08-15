# BUG-EXC-MSG-NOT-OWNED (the assert half)
#
# The message expression of a failing `assert` was evaluated in a block that
# always terminates — a return, or a branch to the except handler — and the
# temps it produced were dropped only *after* that terminator, where a decref
# cannot be emitted.  So every dynamic assert message leaked: 500k iterations
# of `assert i < 0, "m" * 350` reached a 186 MB working set.
#
# Releasing them while the block is still open is safe because `fastpy_raise`
# copies the message into the exception slot's own refcounted string, so what
# the handler reads back does not point at the temp.  These cases exist to
# prove that copy really is independent — a message must stay readable after
# later asserts have raised and after the handler has cleared.

# --- distinct messages, one per iteration ---
msgs = []
for i in [1, 2, 3]:
    try:
        assert i < 0, "bad %d" % i
    except AssertionError as e:
        msgs.append(str(e))
print(msgs)

# --- a message held across later failing asserts ---
held = ""
try:
    assert False, "f" + "irst"
except AssertionError as e:
    held = str(e)
for i in [1, 2]:
    try:
        assert False, "noise %d" % i
    except AssertionError:
        pass
print("held:", held)

# --- the message crosses a function return (the non-try arm) ---
def need_positive(x):
    assert x > 0, "need positive, got " + str(x)
    return x

try:
    need_positive(-5)
except AssertionError as e:
    print("caught:", e)

# --- a message longer than the exception slot's inline capacity ---
try:
    assert False, "x" * 400
except AssertionError as e:
    print("long:", len(str(e)))

# --- messages as dict values, collected without concatenating ---
by_key = {}
for k in ["a", "b"]:
    try:
        assert False, "msg-" + k
    except AssertionError as e:
        by_key[k] = str(e)
print(by_key["a"], by_key["b"])

# --- an assert inside a handler must not disturb the outer message ---
def nested():
    try:
        assert False, "outer assert"
    except AssertionError as e:
        outer = str(e)
        try:
            assert False, "inner assert"
        except AssertionError:
            pass
        return outer

print("nested:", nested())

# --- a passing assert evaluates no message at all ---
def boom():
    print("MESSAGE EVALUATED")
    return "should not appear"

assert True, boom()
print("done")
