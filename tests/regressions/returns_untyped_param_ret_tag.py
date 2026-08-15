"""`return <untyped param>` must report `mixed`, not fall through to `int`.

BUG-RETURNS-UNTYPED-PARAM-RET-TAG.

    def opaque_str():
        return "abcd"

    def echo(v):
        return v

    print(len(echo(opaque_str())))      # 0, should be 4

`_duf_determine_ret_tag` has a "param pass-through" arm that inherits the
parameter's type from the call site, but when the call site never classified
the parameter there was nothing to inherit and control reached the final

    ret_tag = "str" if returns_str else "int"

so a function that literally returns whatever it was handed was declared to
return an int.  `echo` really is FV-ABI and really does return a tagged
`{i32, i64}`, so the *value* was intact; what went wrong is that the caller,
believing `ret_tag == "int"`, ran `_unwrap_return_value` and threw the tag
away.  `len()` then measured a string pointer as an integer and answered 0.

The fix reports `"mixed"` — the honest answer, since the kind is whatever the
caller passed and only the runtime tag can say — and widens
`_callee_returns_mixed` to consult `info.ret_tag` when `_func_ret_types` has no
entry.  The declaration pass is the authority for this one shape because it is
the only pass that can see "returns a parameter"; the CSA chain has no arm for
it and leaves `_func_ret_types` empty, which is why the two must be combined
rather than one deferring to the other.

Binding the result to a name first always worked (`_assign_fv_fast_path` stores
the raw FpyValue), so the bug only ever showed when a call was used directly as
an argument.  Both forms appear below, and they must agree.

An **annotated** parameter is deliberately excluded even when no call site
classified it.  The annotation is evidence, `_duf_select_abi` accepts it as
such and may give the function the bare ABI, and a bare `i64` return has
nowhere to carry a "mixed" tag.  `ann_echo()` covers this.
"""


def opaque_str():
    return "abcd"


def opaque_str2(n):
    return "xy" * n


def opaque_list():
    return [1, 2, 3, 4, 5]


# ── The repro: used directly as an argument, not bound to a name ──

def echo(v):
    return v


print(len(echo(opaque_str())))
print(echo(opaque_str()))
print(len(echo(opaque_str2(3))))


# ── The direct form and the bound form must agree ──

_r = echo(opaque_str())
print(_r, len(_r), len(echo(opaque_str())))


# ── The returned value must survive intact, not merely be counted ──

print(echo(opaque_str()) == "abcd", echo(opaque_str()) + "!")


# ── A conditional return mixing a literal with the parameter ──

def maybe(v, flag):
    if flag:
        return 0
    return v


print(maybe(opaque_str(), False), maybe(opaque_str(), True))
print(len(maybe(opaque_str(), False)))


# ── A list flowing through the same shape ──

def echo_l(v):
    return v


print(len(echo_l(opaque_list())), echo_l(opaque_list())[2])


# ── Scalars must keep working: nothing here should become slower or wrong ──

def echo_i(v):
    return v


def twice(v):
    return v + v


print(echo_i(7), twice(21), echo_i(echo_i(3)))


# ── An annotated parameter keeps the plain int tag ──
# Evidence from the annotation is enough for the bare ABI, which has nowhere
# to put a "mixed" tag, so this shape must be left alone.

def ann_echo(n: int) -> int:
    return n


print(ann_echo(42), ann_echo(ann_echo(9)))


# ── Chained through two pass-throughs ──

def echo_a(v):
    return v


def echo_b(v):
    return echo_a(v)


print(len(echo_b(opaque_str())), echo_b(opaque_str()))


# ── The same chain, but the wrapper is declared before its callee ──
# The declaration pass cannot answer this in one sweep, so it takes the
# fixed-point step in `_duf_propagate_mixed_ret_tags`.

def fwd_wrap(v):
    return fwd_inner(v)


def fwd_wrap2(v):
    return fwd_wrap(v)


def fwd_inner(v):
    return v


print(len(fwd_wrap(opaque_str())), len(fwd_wrap2(opaque_str())),
      fwd_wrap2(opaque_str()))


# ── Nested and closure functions ──

def outer():
    def inner(v):
        return v

    print(len(inner(opaque_str())), inner(opaque_str()))


outer()


# ── The same shapes inside a function and across a loop ──

def in_func():
    print(len(echo(opaque_str())), echo(opaque_str()))
    v = echo(opaque_str())
    print(v, len(v))
    t = 0
    i = 0
    while i < 12:
        t = t + len(echo(opaque_str2(i % 3 + 1)))
        i = i + 1
    print(t)


in_func()
