"""A bare call to a mixed-kind function must keep its runtime tag.

BUG-DIRECT-CALL-LEN-STATIC-TAG.

`mixed_return_tag.py` made the CSA pass *say* `"mixed"` when a function's
returns commit to more than one pointer kind, which fixed every use that went
through a variable. It did not fix the direct form:

    def pick(flag):
        if flag:
            return "abcd"
        return [1, 2, 3]

    len(pick(True))     # 4 via a variable, garbage as written

The reason is that two different places decide what a callee's result is, and
only one of them had been taught about `mixed`:

    v = pick(True)   ->  _assign_fv_fast_path  ->  reads _func_ret_types
    len(pick(True))  ->  _emit_user_call       ->  _unwrap_return_value,
                                                   reads info.static_ret_type

`info.static_ret_type` is fixed in the declaration pass, before call-site
analysis has run, so it is the coarse first guess — `list` for `pick`.
`_unwrap_return_value` then did `_fv_as_ptr(fv)` on a value that was a `str` on
this path, handing `len()` a bare pointer with the tag stripped and the wrong
static kind attached. The damage was not confined to `len`: subscripting gave
an empty result, `in` answered False, and iterating a returned str yielded one
empty item.

The fix is at the same seam as the load-side one. When `_func_ret_types` says
`mixed`, `_emit_user_call` skips the unwrap and hands back the whole tagged
FpyValue; `_emit_expr` already types any `fpy_val`-shaped result as
`VKind.FVALUE`, which is what routes `len`, subscript, iteration and the rest
through runtime dispatch. `_callee_returns_mixed` deliberately consults
`_func_ret_types` rather than `info.ret_tag`, because agreeing with
`_assign_fv_fast_path` is the whole point — if the two disagree then
`v = f(x); len(v)` and `len(f(x))` disagree, which was the bug.

Note the reverse direction is *not* a hazard: a uniform-kind callee never gets
a `mixed` tag, so it keeps its static unwrap and its static downstream paths.
The uniform cases at the bottom are here to hold that line.

One adjacent bug is deliberately *not* covered here, because it is
pre-existing, far broader, and orthogonal — it was verified to misbehave
identically at the parent commit and with a callee of a single fixed kind:

* BUG-PARAM-TYPE-FROM-USER-CALL-ARG — when a parameter's only call-site
  evidence is a user function call, the parameter is left untyped and `len()`
  on it returns 0. This has nothing to do with mixed kinds: `sink(always_list(5))`
  is just as broken as `sink(pick(True))`. Nothing below passes a call result
  straight into another user function.
"""


def pick(flag):
    if flag:
        return "abcd"
    return [1, 2, 3]


def pick3(n):
    if n == 0:
        return "s"
    if n == 1:
        return {"k": 1}
    return [9, 9]


# ── The repro, at module scope and with no intermediate variable ──

print(len(pick(True)), len(pick(False)))
print(len(pick3(0)), len(pick3(1)), len(pick3(2)))


# ── Everything downstream of the call, not just len() ──
# Each of these read the value through the wrong static kind before the fix.

print(pick(True), pick(False))
print(pick(True)[0], pick(False)[0])
print(pick(True)[1:3])
print(str(pick(True)), str(pick3(1)))
print(1 in pick(False), "a" in pick(True))
print(bool(pick(False)), bool(pick(True)))

for c in pick(False):
    print(c)


# ── The call result feeding arithmetic and formatting ──

print(len(pick(True)) + len(pick(False)))
print(len(pick(True)) * 2)
print(f"{len(pick(True))}")
print(len(pick3(0)) + len(pick3(1)) + len(pick3(2)))


# ── A non-constant argument, so the branch is not foldable ──

print(len(pick(1 > 0)), len(pick(1 < 0)))


# ── Every pointer-kind pairing, called directly ──

def bytes_or_str(f):
    if f:
        return b"abc"
    return "de"


def comp_or_str(f):
    if f:
        return [i for i in range(5)]
    return "ab"


def str_or_tuple(f):
    if f:
        return "xyz"
    return (1, 2)


def str_or_set(f):
    if f:
        return "wxyz"
    return {7}


def str_or_dict(f):
    if f:
        return "xy"
    return {"a": 1, "b": 2}


print(len(bytes_or_str(True)), len(bytes_or_str(False)))
print(len(comp_or_str(True)), len(comp_or_str(False)))
print(len(str_or_tuple(True)), len(str_or_tuple(False)))
print(len(str_or_set(True)), len(str_or_set(False)))
print(len(str_or_dict(True)), len(str_or_dict(False)))


# ── The same, in function scope ──

def in_func():
    print(len(pick(True)), len(pick(False)))
    print(pick(True)[0], pick(False)[0])
    print(len(pick(True)[0:2]))
    print(len(pick3(0)), len(pick3(1)), len(pick3(2)))
    print(len(bytes_or_str(False)), len(comp_or_str(True)))
    print(len(str_or_tuple(False)), len(str_or_set(False)))
    print(len(str_or_dict(True)), len(str_or_dict(False)))


# ── A loop: a wrong tag would be re-read every pass ──

def in_loop():
    i = 0
    total = 0
    while i < 40:
        total = total + len(pick(i % 2 == 0))
        i = i + 1
    print(total)


def in_loop_three():
    i = 0
    total = 0
    while i < 30:
        total = total + len(pick3(i % 3))
        i = i + 1
    print(total)


# ── The direct and the via-variable forms must agree ──
# They are decided in two different places, so this is the invariant that
# actually broke.

def both_forms_agree():
    v = pick(True)
    print(len(v) == len(pick(True)))
    w = pick(False)
    print(len(w) == len(pick(False)))
    d = pick3(1)
    print(len(d) == len(pick3(1)))
    print(len(str_or_dict(False)) == len(str_or_dict(False)))


# ── Uniform-kind callees keep their static unwrap ──

def always_str(n):
    return "x" * n


def always_list(n):
    return [n, n]


def always_dict():
    return {"a": 1, "b": 2, "c": 3}


def uniform_unchanged():
    print(len(always_str(3)), len(always_list(4)), len(always_dict()))
    print(always_str(2), always_list(1))
    print(always_str(4)[0], always_list(2)[1])


in_func()
in_loop()
in_loop_three()
both_forms_agree()
uniform_unchanged()
