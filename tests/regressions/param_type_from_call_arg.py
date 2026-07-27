"""A parameter fed only by a user call must still get a type.

BUG-PARAM-TYPE-FROM-USER-CALL-ARG.

When every call site passes a *call result* for a given parameter, the
parameter was left untyped, and operations on it silently produced wrong
answers rather than crashing:

    def always_list(n):
        return [n, n, n]

    def sink(v):
        return len(v)

    print(sink(always_list(5)))     # 0, should be 3

This is not about mixed kinds — `always_list` has one unambiguous return. It is
an ordering problem. `_infer_call_arg_type` cannot resolve `f(helper())` during
the main scan for two independent reasons: `_user_functions` is still empty at
that point, so its user-call branch is dead code there, and
`_csa_propagate_ret_types` has not run yet, so no callee's return type is known.
The argument reads as "unknown", and a parameter whose *only* evidence is such
an argument never gets typed.

`len()` on an untyped parameter answers 0 instead of faulting, which is why
this hid for so long. The other reason it hid: it is enough for one call site
to pass something classifiable. Adding `sink([1, 2])` anywhere types the
parameter and every other call site starts working, so almost any real program
that also passes a literal never sees it.

The fix is `_csa_refine_params_from_call_returns`, a fixed-point step that runs
after `_func_ret_types` is populated and fills slots that are still None. It is
deliberately conservative in one direction and deliberately *not* in the other:

* An **unresolvable** caller at a position poisons that position — the slot
  stays untyped, preserving the "unknown doesn't override known" rule the main
  merge relies on. `poisoned()` below covers this.
* Callers that all resolve but **disagree** get `mixed`, not None. Every caller
  is known there; they just are not the same kind, which is what `mixed` means,
  and the merge already accepts it as a parameter tag. Leaving it None would
  keep the untyped ABI and go back to answering 0. `two_kinds()` covers this,
  and it is the case that made the first draft of the fix still print 0.

A slot the main merge already decided is never overridden — `already_typed()`
below is called with both a literal and a call result.

Coverage is bounded by what `_func_ret_types` records, which is
list/dict/tuple/float/mixed but **not** str/bytes/set: a plain `return "abcd"`
has no arm in that chain, so a parameter fed only by a str-returning function
is still untyped. That gap is on the callee side and is tracked separately;
nothing below depends on it.
"""


def always_list(n):
    return [n, n, n]


def always_dict():
    return {"a": 1, "b": 2}


def always_tuple():
    return (1, 2, 3, 4)


def pick(flag):
    if flag:
        return "abcd"
    return [1, 2, 3]


# ── The repro: a parameter whose only evidence is a call result ──

def sink(v):
    return len(v)


def sink_d(v):
    return len(v)


def sink_t(v):
    return len(v)


print(sink(always_list(5)), sink_d(always_dict()), sink_t(always_tuple()))


# ── The parameter must be usable, not merely counted ──

def uses_fully(v):
    t = 0
    for e in v:
        t = t + e
    return t + len(v) + v[0]


print(uses_fully(always_list(7)))


# ── A mixed-kind callee reaching a parameter ──

def mixed_param(v):
    return len(v)


print(mixed_param(pick(True)), mixed_param(pick(False)))


# ── Resolvable but disagreeing callers become mixed, not untyped ──
# The first draft of the fix left this None and still printed 0.

def two_kinds(v):
    return len(v)


print(two_kinds(always_list(4)), two_kinds(always_dict()))


def three_kinds(v):
    return len(v)


print(three_kinds(always_list(2)), three_kinds(always_dict()),
      three_kinds(always_tuple()))


# ── An unresolvable caller leaves the slot untyped, and must still work ──

def poisoned(v, n):
    return len(v) + n


w = [9, 9, 9, 9, 9]
print(poisoned(always_list(2), 1), poisoned(w, 2))


# ── A slot the main merge already typed must not be overridden ──

def already_typed(v):
    return len(v)


print(already_typed([1, 2, 3, 4, 5, 6]), already_typed(always_list(3)))


# ── Keyword call sites disable refinement for that callee ──
# Positional slots cannot be aligned through a keyword, so guessing could type
# the wrong parameter. These must keep working, whatever they end up typed as.

def kw_called(v, n=1):
    return len(v) + n


print(kw_called(always_list(3), n=2), kw_called(w))


# Star-args call sites are blocked for the same reason. Both a no-default and a
# defaulted callee are exercised; the latter used to raise IndexError at runtime
# independently of any of this (BUG-STARARG-SPLAT-DEFAULT-PARAM, since fixed —
# `stararg_splat_default_param.py` covers it).

def splat_target(a, b):
    return a + b


def splat_defaulted(a, b=10):
    return a + b


_pair = [3, 4]
_one = [3]
print(splat_target(*_pair), splat_defaulted(*_one), splat_defaulted(*_pair))


# ── The same shapes inside a function, and across a loop ──

def in_func():
    print(sink(always_list(4)), sink_d(always_dict()))
    print(mixed_param(pick(True)), mixed_param(pick(False)))
    print(two_kinds(always_list(6)), two_kinds(always_dict()))
    print(uses_fully(always_list(3)))
    t = 0
    i = 0
    while i < 20:
        t = t + mixed_param(pick(i % 2 == 0))
        i = i + 1
    print(t)


def nested_calls():
    # A call result feeding a call result.
    print(sink(always_list(sink(always_list(2)))))


in_func()
nested_calls()
