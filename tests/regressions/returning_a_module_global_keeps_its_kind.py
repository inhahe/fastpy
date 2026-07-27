"""A function that returns a module-level global returns its kind too.

BUG-RETURN-OF-GLOBAL-LOSES-ITS-KIND.

A function's LLVM return type and its return tag are both inferred from
four sets — `str_vars`, `list_vars`, `dict_vars`, `obj_vars` — and those
sets are built from two sources: the function's own assignments, and its
parameters as described by the call sites.  A module-level global that
the function merely *reads* is neither, so it was in none of the sets,
matched none of the `return <Name>` arms, and fell through to the `int`
default:

    s = "hello"

    def direct():
        return s

    print(direct())     # 140697798825664, a live pointer read as an int

The kind was never actually unknown.  The CSA pre-pass records every
module-level name's tag in `_csa_var_types`, and its own `_func_ret_types`
already said `direct: 'str'` — the per-function declaration pass simply
had no way to ask.  Note that the bare-i64 ABI is chosen from the same
inference, so a fix that set only the *tag* would still have handed the
caller a return slot with nowhere to put a pointer; the return *type* had
to widen at the same time.

Every section below is a global of some kind, returned both directly and
through one local alias, since the alias is what proves the fix works by
seeding the kind sets rather than by adding one arm for a bare `Name`.
The last sections are the cases that must NOT change: a name the function
binds itself is its own, not the module's.
"""


# ── str: the original report ─────────────────────────────────────────────

s = "hello"


def direct():
    return s


def via_local():
    t = s
    return t


def via_two_hops():
    a = s
    b = a
    return b


def use_it():
    return len(s)


def concat():
    return s + "!"


print(direct(), len(direct()), direct() == "hello")
print(via_local(), len(via_local()))
print(via_two_hops(), via_two_hops().upper())
print(use_it(), concat())


# ── float: the return type widens to double, not just the tag ────────────

f = 1.5


def get_f():
    return f


def alias_f():
    q = f
    return q


def half_f():
    return f / 2


print(get_f(), get_f() == 1.5, get_f() + 1.0)
print(alias_f(), alias_f() * 2)
print(half_f())


# ── int: the default was already right and must stay right ───────────────

n = 7


def get_n():
    return n


def alias_n():
    q = n
    return q


print(get_n(), get_n() + 1, alias_n() * 3)


# ── list ─────────────────────────────────────────────────────────────────

xs = [10, 20, 30]


def get_xs():
    return xs


def alias_xs():
    q = xs
    return q


def sum_xs():
    total = 0
    for v in get_xs():
        total += v
    return total


print(get_xs(), len(get_xs()), get_xs()[1])
print(alias_xs(), len(alias_xs()), alias_xs()[2])
print(sum_xs(), get_xs()[1:])


# ── dict ─────────────────────────────────────────────────────────────────

d = {"a": 1, "b": 2}


def get_d():
    return d


def alias_d():
    q = d
    return q


print(len(get_d()), get_d()["b"], sorted(get_d()))
print(len(alias_d()), alias_d()["a"])


# ── An object of a user class ────────────────────────────────────────────

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def total(self):
        return self.x + self.y


origin = Point(3, 4)


def get_origin():
    return origin


def alias_origin():
    q = origin
    return q


print(get_origin().x, get_origin().total())
print(alias_origin().y, alias_origin().total())


# ── A name the function binds is its own, not the module's ───────────────
# Each of these would break if the module's tag were applied to a name the
# scope rebinds.  A parameter, a plain assignment, a loop target, a `with`
# or comprehension target and a nested def all shadow.

msg = "global-msg"


def shadow_assign():
    msg = 41
    return msg + 1


def shadow_param(msg):
    return msg


def shadow_loop():
    total = 0
    for msg in [1, 2, 3]:
        total += msg
    return total


def shadow_comprehension():
    return sum([msg for msg in [4, 5]])


def shadow_nested():
    def msg():
        return 9
    return msg()


print(shadow_assign(), shadow_param(5), shadow_param("x"))
print(shadow_loop(), shadow_comprehension(), shadow_nested())


# ── `global` rebinding: the module tag is not evidence after it ──────────

counter = 0


def bump():
    global counter
    counter = counter + 1
    return counter


print(bump(), bump(), counter)


# ── A global the module rebinds is not claimed at all ────────────────────
# `_csa_var_types` is last-writer-wins and has no arm for a plain int, so a
# module that says `x = 10` and later `x = "global"` records `str` — a tag
# that is wrong for every call made before the second assignment.  Reading
# that as a *return type* compiled `return x` to a str return and printed
# the integer 10 through it, which crashed; `tests/cpython_adapted/
# test_scope.py` is exactly that program and caught it.  A name the module
# binds more than once, or that any `global` statement names — since the
# rebinding is then inside a function body the module-level walk never
# enters — is therefore not claimed, and keeps the old untyped behaviour.
# (Declining even when two bindings agree is deliberate: knowing they agree
# means classifying each assignment separately, and a second copy of that
# classifier is a worse thing to own than a missed refinement.)
#
# The kind-changing rebind is separately broken in the *body* — see
# BUG-GLOBAL-KIND-CHANGING-REBIND-USES-STALE-TAG — so only the shapes that
# are correct today are asserted here.

first = 1
first = 2


def peek_first():
    return first


print(peek_first(), peek_first() + 1)

owned = "start"


def set_owned():
    global owned
    owned = "changed"
    return 1


def read_owned():
    return len(owned)


print(read_owned())
print(set_owned())
print(read_owned())


# ── A global read but not returned must not colour the return ────────────
# `int(f)` and `len(s)` produce integers even though they mention a float
# and a str global; the kind sets must not leak into the float-evidence
# walk that types the enclosing function.

def as_int():
    return int(f)


def name_len():
    return len(s)


def picks_int():
    if len(s) > 3:
        return 1
    return 0


print(as_int(), name_len(), picks_int())
print("end")
