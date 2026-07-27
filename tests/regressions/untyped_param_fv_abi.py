"""A parameter with no known type must not be given the bare ABI.

BUG-UNTYPED-PARAM-BARE-ABI.

`_duf_select_abi` chose the bare-type ABI whenever every parameter's LLVM type
was scalar. But `param_types` falls back to `i64` when nothing is known about a
parameter, so "no evidence at all" and "known to be an int" were
indistinguishable by the time the ABI was picked, and an untyped parameter
counted as a scalar one:

    def sink(v):
        return len(v)

    def opaque():
        return "abcd"

    print(sink(opaque()))       # 0, should be 4

Bare ABI has nowhere to put a runtime tag. The caller unwrapped the callee's
tagged `FpyValue` down to a naked `i64` and the body then read a string pointer
as an integer — `len()` answered 0 rather than faulting, which is why this hid.
`sink` was emitted as

    define internal i64 @fastpy.user.sink(i64 %v)

and is now

    define internal {i32, i64} @fastpy.user.sink({i32, i64} %v)

The fix requires *positive* evidence for the bare ABI: every parameter must
either carry an annotation or have been classified at some call site.
Inferring "scalar" from silence is what produced the wrong answer.

This is the shared root cause behind several separately-logged symptoms, which
is why it was worth fixing at the ABI rather than patched at each use:
BUG-PARAM-TYPE-FROM-USER-CALL-ARG (`len()` → 0 on a parameter fed only by a
call), BUG-SPLAT-DEFAULTED-SLOT-TYPE (a `"mixed"` parameter tag still landed on
a bare `i64` instead of dispatching), and BUG-SUBSCRIPT-UNTYPED-PARAM-BRIDGE.

The last of those is **not** fixed by this change and nothing below subscripts
or iterates an untyped parameter: `s[0]` on an FV-ABI parameter still faults,
because the subscript path has no runtime-tag dispatch arm. The ABI change is a
prerequisite for that fix — the tag now survives the call — but the subscript
itself is tracked separately.

`str` is the interesting case throughout, because `_func_ret_types` has no arm
for a plain `return "abcd"`; a list- or dict-returning callee gets its
parameter typed by `_csa_refine_params_from_call_returns` and so never reached
the bare ABI in the first place.

One neighbour was deliberately absent here, verified at the time to behave
identically before and after this change: `bytes` flowing through an untyped
parameter lost its tag, so `len()` on it answered 0 and `print()` showed a
pointer. That was BUG-BYTES-RETURN-TAG-LOST, since fixed;
`bytes_return_tag.py` covers it directly.

`len(echo(opaque_str()))`, where `echo` just returns its own untyped parameter,
was also wrong here at the time — the declaration pass guessed `ret_tag="int"`
for such a function and the call site unwrapped to that, so only the
bound-to-a-name form appears below. That is BUG-RETURNS-UNTYPED-PARAM-RET-TAG,
since fixed; `returns_untyped_param_ret_tag.py` covers it directly.
"""


def opaque_str():
    return "abcd"


def opaque_str2(n):
    return "xy" * n


# ── The repro: the only evidence is a str-returning call ──

def sink(v):
    return len(v)


print(sink(opaque_str()), sink(opaque_str2(3)))


# ── The value must survive intact, not merely be counted ──

def echo(v):
    return v


def show(v):
    print(v)


_r = echo(opaque_str())
print(_r, len(_r))
show(opaque_str())


# ── Comparisons and concatenation on an untyped parameter ──

def cmp_eq(v):
    return v == "abcd"


def concat(v):
    return v + "!"


print(cmp_eq(opaque_str()), cmp_eq(opaque_str2(1)))
print(concat(opaque_str()))


# ── An untyped parameter used arithmetically must still be fast and right ──
# These have a classifiable call site, so they keep the bare ABI; the point is
# that the stricter rule did not take it away from them.

def add(a, b):
    return a + b


def fma(a, b, c):
    return a * b + c


print(add(2, 3), fma(2, 3, 4))


# ── Annotations count as evidence, with no call site at all ──

def annotated(n: int) -> int:
    return n * 2


print(annotated(21))


# ── Nested and closure functions, where the untyped params actually live ──

def outer():
    def inner(x):
        return x * 3

    def uses_call(v):
        return len(v)

    print(inner(4), uses_call(opaque_str()))


outer()


def make_adder(x):
    def adder(i):
        return x + i
    return adder


_a = make_adder(10)
print(_a(5), _a(7))


# ── Recursion: the parameter's only evidence is the recursive call ──

def count_down(n):
    if n <= 0:
        return 0
    return 1 + count_down(n - 1)


print(count_down(6))


# ── The same shapes inside a function and across a loop ──

def in_func():
    v = echo(opaque_str())
    print(sink(opaque_str()), v, len(v))
    t = 0
    i = 0
    while i < 12:
        t = t + sink(opaque_str2(i % 3 + 1))
        i = i + 1
    print(t)


in_func()
