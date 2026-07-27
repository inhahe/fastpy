# BUG-UNBOUND-NATIVE-LOCAL-READS-STACK
#
# "Never assigned" is a value a variable can have, and it needs somewhere to
# live.  An FV slot has room for it — `FPY_TAG_UNDEF` in the tag word, written
# on entry and checked on every load — but a *native* slot (a bare `i64`, or a
# `double`, or an `i8*`) is all payload and no tag, so there is nothing to
# write and nothing to check.  Two things put a local in a native slot: bare-ABI
# mode, and a `--typed` annotation.  Both did it to locals that a read could
# reach before any store did, and the read then returned whatever the stack
# happened to hold:
#
#     for a in range(0):
#         z = 0
#     print(z)          # printed 0
#
#     if False:
#         w = 1
#     print(w)          # printed 2458834108416, then 1988293820416, ...
#
# So `_names_maybe_unbound` now answers "which locals can be read before they
# are bound?" for real — intersecting `if` branches, scanning loop bodies twice
# so the second pass models "not the first iteration", treating a bare
# `x: int` as a declaration that binds nothing — and a scope with any such
# local is disqualified from the bare ABI exactly the way a scope that touches
# a BigInt is.  Same argument in both cases: the value needs a tag the slot
# cannot carry.
#
# That alone was not enough.  The load also has to *do* the check, and it was
# skipping it whenever `_definitely_assigned` held the name — but that set
# records that a store was *emitted*, and a store inside a loop that runs zero
# times is emitted just the same.  The skip now defers to the analysis.
#
# The exception differs by scope: a module-level read raises NameError, a
# function-level one UnboundLocalError — which is a *subclass* of NameError,
# so `except NameError:` has to catch it, and does, because handler matching
# walks the class hierarchy (BUG-BUILTIN-EXC-HIERARCHY-NOT-MATCHED).

# --- a loop that never runs ---
def loop_zero(n):
    for _ in range(n):
        z = 0
    return z


try:
    loop_zero(0)
except UnboundLocalError as e:
    print("loop_zero(0):", type(e).__name__)
print("loop_zero(1):", loop_zero(1))


# --- a branch that is never taken ---
def branch(t):
    if t:
        v = 1
    return v


try:
    branch(0)
except UnboundLocalError as e:
    print("branch(0):", type(e).__name__)
print("branch(1):", branch(1))


# --- the last value of a loop variable, when the loop had no iterations ---
def last_of(n):
    for i in range(n):
        last = i * 2
    return last


try:
    last_of(0)
except UnboundLocalError:
    print("last_of(0): unbound")
print("last_of(3):", last_of(3))


# --- every slot shape, not just i64 ---
def f_float(t):
    if t:
        x = 1.5
    return x


def f_str(t):
    if t:
        s = "hi"
    return s


def f_list(t):
    if t:
        m = [1, 2]
    return m


try:
    f_float(0)
except UnboundLocalError:
    print("float unbound")
print("float bound:", f_float(1))

try:
    f_str(0)
except UnboundLocalError:
    print("str unbound")
print("str bound:", f_str(1))

try:
    f_list(0)
except UnboundLocalError:
    print("list unbound")
print("list bound:", f_list(1))


# --- an else arm binds too, so both arms binding means bound ---
def both_arms(t):
    if t:
        q = "yes"
    else:
        q = "no"
    return q


print(both_arms(1), both_arms(0))


# --- one arm binding is not enough, even when the other returns ---
def one_arm_returns(t):
    if t:
        r = 5
    else:
        return "early"
    return r


print(one_arm_returns(0), one_arm_returns(1))


# --- a read *before* the assignment in straight-line code ---
# (The read is its own statement.  `y = y + 1` also raises, but the `+` then
# runs anyway on the garbage value and its TypeError replaces the pending
# UnboundLocalError — BUG-PENDING-EXC-CLOBBERED-IN-FUNCTION, which is about
# codegen not bailing out of a function mid-statement, not about this fix.)
def read_then_write():
    try:
        seen = y
    except UnboundLocalError:
        return "caught"
    y = 1
    return seen


print(read_then_write())


# --- `del` unbinds a local that was bound ---
def deleted():
    d = 1
    del d
    try:
        return d
    except UnboundLocalError:
        return "deleted"


print(deleted())


# --- an annotation declares without binding ---
def annotated(t):
    a: int
    if t:
        a = 7
    return a


try:
    annotated(0)
except UnboundLocalError:
    print("annotated(0): unbound")
print("annotated(1):", annotated(1))


# --- a parameter is always bound, however it is spelled ---
# (`*args`/`**kwargs` are parameters too, but calling those shapes is broken
# for unrelated reasons — BUG-DEFAULT-PLUS-VARARG-CALL-BROKEN and
# BUG-EMPTY-KWARGS-CALL-SEGFAULTS — so they are not exercised here.)
def params(p, q=2):
    return p, q


def kwonly(p, *, k=3):
    return p, k


print(params(1), params(1, 5))
print(kwonly(1), kwonly(1, k=9))


# --- while-loop bodies follow the same rule as for-loops ---
def while_zero(n):
    i = 0
    while i < n:
        w = i
        i += 1
    return w


try:
    while_zero(0)
except UnboundLocalError:
    print("while_zero(0): unbound")
print("while_zero(2):", while_zero(2))


# --- a value bound in the loop body *is* visible on later iterations ---
def carry(n):
    total = 0
    for i in range(n):
        if i:
            total += prev
        prev = i
    return total


print(carry(0), carry(1), carry(4))


# --- `try`/`finally`: only the finally body is guaranteed to have run ---
def in_finally(t):
    try:
        if t:
            raise ValueError("x")
        a = 1
    except ValueError:
        pass
    finally:
        b = 2
    return b


print(in_finally(0), in_finally(1))


# --- an unbound local raised inside a callee reaches the caller's handler ---
def raises_unbound():
    if 0:
        missing_local = 1
    return missing_local


def caller():
    try:
        raises_unbound()
    except UnboundLocalError:
        return "propagated"
    return "no"


def raises_unbound2():
    if 0:
        missing2 = 1
    return missing2


def caller2():
    try:
        raises_unbound2()
    except NameError:
        return "as NameError"
    return "no"


print(caller(), caller2())


# --- module scope says NameError, and that is not the same message ---
if 0:
    module_only = 1

try:
    print(module_only)
except NameError as e:
    print("module:", type(e).__name__)

try:
    print(never_written_at_all)
except NameError as e:
    print("module2:", type(e).__name__)


# --- a global read from inside a function still resolves ---
g = 10


def reads_global():
    return g


print(reads_global())


def writes_global():
    global g
    g = 20
    return g


print(writes_global(), g)


# --- a name that is global *and* assigned later in the function is local ---
def shadows(t):
    try:
        return g2
    except (NameError, UnboundLocalError):
        g2 = 1
        return "shadowed"


g2 = 99
print(shadows(1))


# --- bound before the loop, reassigned in it: never unbound ---
def prebound(n):
    p = -1
    for i in range(n):
        p = i
    return p


print(prebound(0), prebound(3))


# --- nested function: its own locals, its own analysis ---
def outer(t):
    def inner(u):
        if u:
            k = 1
        return k

    try:
        return inner(t)
    except UnboundLocalError:
        return "inner unbound"


print(outer(0), outer(1))


# --- the raise happens once, and does not corrupt later state ---
count = 0


def counted(t):
    global count
    count += 1
    if t:
        c = t
    return c


# (The call is its own statement: `print(t, counted(t))` would emit `t` before
# evaluating the argument that raises — BUG-PRINT-EMITS-BEFORE-ARGS-RAISE.)
for t in (0, 1, 0, 2):
    try:
        r = counted(t)
    except UnboundLocalError:
        r = "unbound"
    print(t, r)
print("count:", count)
