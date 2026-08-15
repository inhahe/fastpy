# BUG-PENDING-EXC-CLOBBERED-IN-FUNCTION
#
# A raise sets a flag.  Something has to look at that flag and stop, and
# `_emit_try_bail_if_exc` is what emitted the looking — but it only had two
# arms.  Inside a `try` it branched to the handler; at module level it called
# `exc_unhandled`; and inside a function that was neither it emitted *nothing*.
# So codegen carried straight on with the rest of the statement, the next
# operation ran on whatever the failed one left in the register, and its
# exception overwrote the real one:
#
#     def f(a):
#         return (1 // a) + "s"     # ZeroDivisionError, then TypeError
#
# `except Exception as e:` reported TypeError.  The same hole let side effects
# past a raise: `xs.append(1 // a); xs.append(99)` appended both.
#
# Functions now have a third arm — a lazily created `fn.exc_exit` block that
# pops the shadow stack, releases the scope's locals and returns a zero — so a
# frame unwinds the way a `return` does and the caller's own check picks the
# exception up.
#
# That exposed the other half.  A `finally` body, and the `__exit__` a `with`
# ends in, run *while* the exception is propagating, and they are ordinary
# code: once callees started honouring the pending flag, the first statement
# of the cleanup unwound instead of cleaning up, and `__exit__` never ran.  So
# the exception is now moved aside for the duration (`fastpy_exc_save`) and put
# back after (`fastpy_exc_restore`) — or discarded, when `__exit__` returned
# truthy to suppress it, or when the cleanup `return`s, both of which are
# Python's own rules.  A raise *inside* the cleanup keeps its own exception,
# because in Python a raise in a `finally` replaces the one it interrupted.


# --- the original shape: a second op must not overwrite the first's raise ---
def two_ops(a):
    return (1 // a) + "s"


def two_ops_ok(a):
    return str(1 // a) + "s"


try:
    two_ops(0)
except Exception as e:
    print("two_ops:", type(e).__name__)
print("two_ops ok:", two_ops_ok(1))


# --- side effects after the raise must not happen ---
def appends(xs, a):
    xs.append(10 // a)
    xs.append(99)
    return xs


acc = []
try:
    appends(acc, 0)
except ZeroDivisionError:
    print("appends: ZeroDivisionError")
print("appends acc:", acc)
print("appends ok:", appends(acc, 2))


# --- through several frames, none of which has a try ---
def lvl3(a):
    return 10 // a


def lvl2(a):
    return lvl3(a) + 1


def lvl1(a):
    return lvl2(a) * 2


try:
    lvl1(0)
except ZeroDivisionError as e:
    print("deep:", type(e).__name__)
print("deep ok:", lvl1(2))


# --- every return shape has somewhere to go ---
def ret_str(a):
    return "x" + str(10 // a)


def ret_float(a):
    return 1.5 / a


def ret_list(a):
    return [10 // a]


def ret_none(xs, a):
    xs.append(10 // a)


for name, thunk in (("str", ret_str), ("float", ret_float),
                    ("list", ret_list)):
    try:
        thunk(0)
    except ZeroDivisionError:
        print(name, "raises")
print("str ok:", ret_str(5))
print("float ok:", ret_float(3))
print("list ok:", ret_list(5))

void_acc = []
try:
    ret_none(void_acc, 0)
except ZeroDivisionError:
    print("none raises")
print("none acc:", void_acc)
ret_none(void_acc, 5)
print("none acc2:", void_acc)


# --- a method unwinds like a function ---
class C:
    def __init__(self, n):
        self.n = n

    def div(self, a):
        return self.n // a


c = C(100)
try:
    c.div(0)
except ZeroDivisionError:
    print("method raises")
print("method ok:", c.div(4))


# --- the exception class is the raised one, not the next op's ---
def wrong_class(kind):
    if kind == "index":
        return [1, 2][9] + "s"
    if kind == "key":
        return {"a": 1}["z"] + "s"
    if kind == "value":
        return int("q") + "s"
    return 1 // 0 + "s"


for kind in ("index", "key", "value", "zero"):
    try:
        wrong_class(kind)
    except Exception as e:
        print(kind, "->", type(e).__name__)


# --- an explicit raise, not a runtime error ---
def explicit(a):
    if a:
        raise ValueError("boom")
    return "fine"


try:
    explicit(1)
except ValueError as e:
    print("explicit:", str(e))
print("explicit ok:", explicit(0))


# --- finally still runs while unwinding, and can do real work ---
def with_finally(a, log):
    try:
        return 10 // a
    finally:
        log.append("cleanup")
        log.append(len(log))


lg = []
try:
    with_finally(0, lg)
except ZeroDivisionError:
    print("finally: ZeroDivisionError")
print("finally log:", lg)
print("finally ok:", with_finally(2, lg), lg)


# --- a finally that calls a function, which is the case that broke ---
def note(log, tag):
    log.append(tag)
    log.append(len(log))
    return len(log)


def calls_in_finally(a, log):
    try:
        return 10 // a
    finally:
        note(log, "in-finally")


lg2 = []
try:
    calls_in_finally(0, lg2)
except ZeroDivisionError:
    print("call-in-finally: ZeroDivisionError")
print("call-in-finally log:", lg2)


# --- nested finallys unwind outward, each doing its work ---
def nested_finally(a, log):
    try:
        try:
            return 10 // a
        finally:
            note(log, "inner")
    finally:
        note(log, "outer")


lg3 = []
try:
    nested_finally(0, lg3)
except ZeroDivisionError:
    print("nested: ZeroDivisionError")
print("nested log:", lg3)


# --- a raise inside the finally replaces the one it interrupted ---
def raise_in_finally(a):
    try:
        return 10 // a
    finally:
        raise ValueError("from finally")


try:
    raise_in_finally(0)
except Exception as e:
    print("raise-in-finally:", type(e).__name__, str(e))


# --- a return inside the finally discards the exception ---
def return_in_finally(a):
    try:
        return 10 // a
    finally:
        return "swallowed"


print("return-in-finally:", return_in_finally(0), return_in_finally(5))


# --- the same, run enough times that an unbalanced save would show ---
def loop_return_in_finally(n):
    out = []
    for i in range(n):
        out.append(return_in_finally(0))
    return len(out)


print("loop return-in-finally:", loop_return_in_finally(200))


def loop_finally(n):
    total = 0
    for i in range(n):
        try:
            total += 10 // (i % 3)
        except ZeroDivisionError:
            total += 1
        finally:
            total += 1
    return total


print("loop finally:", loop_finally(300))


# --- with: __exit__ runs, and a falsy result does not suppress ---
class Tracked:
    def __init__(self, name, log):
        self.name = name
        self.log = log

    def __enter__(self):
        self.log.append("enter " + self.name)
        return self

    def __exit__(self, a, b, c):
        self.log.append("exit " + self.name)


wl = []
try:
    with Tracked("t", wl):
        raise KeyError("k")
except KeyError:
    wl.append("caught")
print("with log:", wl)


# --- a truthy __exit__ suppresses ---
class Swallow:
    def __enter__(self):
        return self

    def __exit__(self, a, b, c):
        print("swallow exit")
        return True


with Swallow():
    raise RuntimeError("gone")
print("after swallow")


# --- nested with, both running their __exit__ on the way out ---
wl2 = []
try:
    with Tracked("outer", wl2):
        with Tracked("inner", wl2):
            raise IndexError("i")
except IndexError:
    wl2.append("caught")
print("nested with:", wl2)


# --- with, where the raise happens inside a called function ---
def raiser(a):
    return 10 // a


wl3 = []
try:
    with Tracked("call", wl3):
        raiser(0)
except ZeroDivisionError:
    wl3.append("caught")
print("with call:", wl3)


# --- a with inside a function, unwinding past the function boundary ---
# (The result is assigned rather than returned from inside the body: a
# `return` inside a `with` skips __exit__ entirely — the finally stack gets
# an empty placeholder for the with — which is BUG-RETURN-IN-WITH-SKIPS-EXIT,
# a different hole from this one.)
def with_in_fn(a, log):
    with Tracked("fn", log):
        out = raiser(a)
    return out


wl4 = []
try:
    with_in_fn(0, wl4)
except ZeroDivisionError:
    wl4.append("caught")
print("with in fn:", wl4)
print("with in fn ok:", with_in_fn(5, wl4), wl4)


# --- the message survives being moved aside and put back ---
def msg_carrier(a):
    if a:
        raise ValueError("message " + str(a))
    return "no"


def msg_with_finally(a, log):
    try:
        return msg_carrier(a)
    finally:
        note(log, "m")


seen = []
lg4 = []
for i in (1, 2, 3):
    try:
        msg_with_finally(i, lg4)
    except ValueError as e:
        seen.append(str(e))
print("messages:", seen)


# --- an inner handler catches, and the function returns normally after ---
def inner_catches(a):
    try:
        return 10 // a
    except ZeroDivisionError:
        return -1


print("inner:", inner_catches(0), inner_catches(5))


# --- a loop that raises partway leaves exactly what ran ---
def partial_loop(n, log):
    for i in range(n):
        log.append(10 // (i - 1))
    return "done"


lg5 = []
try:
    partial_loop(4, lg5)
except ZeroDivisionError:
    print("partial: ZeroDivisionError")
print("partial log:", lg5)
