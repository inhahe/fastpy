"""A function whose returns disagree on kind must be typed `mixed`, not guessed.

BUG-MODULE-DOCSTRING-UNBOXES-GLOBAL.

The CSA return-type pass walked every `ast.Return` in a function and
*overwrote* `_func_ret_types[fname]` each time, so it was
last-classifiable-return-wins:

    def pick(flag):
        if flag:
            return "abcd"
        return [1, 2, 3]

`return "abcd"` matched no branch in that chain (there is no str-Constant arm),
so `return [1, 2, 3]` wrote `"list"` unopposed and `pick` was typed `list:int`.
`len(pick(True))` then took the static `fastpy_list_length` path on a string and
printed 0.

The title says "docstring" because that is how it was found, and the trigger is
genuinely absurd: `_gen_detect_bare_abi` disables bare-ABI for module-level code
if any module-level statement contains a string constant, and a module docstring
*is* an `ast.Expr(Constant(str))`. So merely having a docstring moved module
code off the bare-ABI path. Both paths stored the same (wrong) `list:int` tag —
the difference was only in the load:

    bare-ABI   _load_variable -> raw load of the alloca -> {i32, i64}, tag intact
    FpyValue   _load_variable -> _unwrap_fv_for_tag -> _fv_as_ptr -> i8*, tag gone

so the no-docstring build was correct *by accident*, and every regression test —
all of which have docstrings — ran the broken path. That is why the cases below
matter at module scope specifically, and why this file's own docstring is load-
bearing.

The fix is on the producer only. `_unwrap_fv_for_tag` already returns the whole
FpyValue for `VKind.MIXED`, and `VKind.MIXED.is_ptr` is False so it never
reaches `_fv_as_ptr`; it was enough to make the CSA pass *say* `"mixed"` when
the returns commit to more than one pointer kind.

`_csa_returns_disagree` is deliberately scoped to **pointer** kinds read
straight off the AST. An unclassifiable return (a name, a call, a binop) counts
as no constraint rather than as a conflict — otherwise every `return helper()`
would go MIXED. `return None` and scalar returns are excluded too: the former is
ubiquitous beside `return [...]` and already tolerated, and the latter is
settled by a separate mechanism (the i64-vs-double LLVM return type) that
"mixed" would disrupt. Both exclusions are exercised below.

This file covers only the path where the call result reaches a *variable*.
There is a second decision site — `_emit_user_call`, for a bare call expression
with no intermediate name — which was still unwrapping by the coarse static
type when this file was written, so everything below binds the call to a name
first. That is BUG-DIRECT-CALL-LEN-STATIC-TAG, since fixed;
`direct_call_mixed_tag.py` covers it, including the invariant that the two
forms agree.

One adjacent bug is deliberately *not* covered here, because it is
pre-existing and orthogonal — it was verified to misbehave identically at the
parent commit, so this change neither caused nor fixed it:

* BUG-MIXED-SCALAR-RETURN-TAG — a function returning `1` on one branch and
  `2.5` on another prints the float's bit pattern as an int. Scalars are out of
  scope for `_csa_returns_disagree` by design (see above).
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


# ── The original repro, at module scope, where the static path was taken ──

r = pick(True)
print(r, len(r))
s = pick(False)
print(s, len(s))

a = pick3(0)
b = pick3(1)
c = pick3(2)
print(a, len(a))
print(b, len(b))
print(c, len(c))


# ── Every pointer kind pairing, so no single kind is special-cased ──

def str_or_dict(f):
    if f:
        return "xy"
    return {"a": 1, "b": 2}


def list_or_dict(f):
    if f:
        return [1, 2, 3, 4]
    return {"a": 1}


def str_or_tuple(f):
    if f:
        return "xyz"
    return (1, 2)


def str_or_set(f):
    if f:
        return "wxyz"
    return {7}


def bytes_or_str(f):
    if f:
        return b"abc"
    return "de"


def comp_or_str(f):
    # A comprehension is classifiable, so it constrains the kind.
    if f:
        return [i for i in range(5)]
    return "ab"


def fstring_or_list(f, n):
    # So is an f-string: JoinedStr reads as str.
    if f:
        return f"v={n}"
    return [n, n, n]


def pairings():
    x = str_or_dict(True)
    y = str_or_dict(False)
    print(len(x), len(y))
    x = list_or_dict(True)
    y = list_or_dict(False)
    print(len(x), len(y))
    x = str_or_tuple(True)
    y = str_or_tuple(False)
    print(len(x), len(y))
    x = str_or_set(True)
    y = str_or_set(False)
    print(len(x), len(y))
    x = bytes_or_str(True)
    y = bytes_or_str(False)
    print(len(x), len(y))
    x = comp_or_str(True)
    y = comp_or_str(False)
    print(len(x), len(y))
    x = fstring_or_list(True, 7)
    y = fstring_or_list(False, 7)
    print(len(x), len(y))


# ── The same pairings at module scope — the path the docstring switched ──

m1 = str_or_dict(True)
m2 = str_or_dict(False)
print(len(m1), len(m2))
m3 = str_or_tuple(True)
m4 = str_or_tuple(False)
print(len(m3), len(m4))
m5 = comp_or_str(True)
m6 = comp_or_str(False)
print(len(m5), len(m6))
m7 = fstring_or_list(True, 7)
m8 = fstring_or_list(False, 7)
print(len(m7), len(m8))


# ── Exclusion 1: `return None` must NOT make a function mixed ──
# This is the common "a list or nothing" shape; typing it MIXED would push a
# great deal of ordinary code onto the slow runtime-dispatch paths.

def list_or_none(f):
    if f:
        return [1, 2, 3]
    return None


def maybe():
    v = list_or_none(True)
    print(v, len(v), v[0])
    print(list_or_none(False))


# ── Exclusion 2: an unclassifiable return is no constraint, not a conflict ──
# `_sub(n)` cannot be read off the AST; if it counted as a distinct kind these
# would all be MIXED and the uniform cases below would lose their static paths.

def _sub(n):
    return [n, n]


def calls_only(n):
    if n > 0:
        return _sub(n)
    return _sub(-n)


def call_or_literal(n):
    if n > 0:
        return _sub(n)
    return [0]


def unclassifiable():
    x = calls_only(2)
    y = call_or_literal(3)
    z = call_or_literal(-3)
    print(x, len(x), x[0])
    print(y, len(y))
    print(z, len(z))


# ── Uniform-kind functions must keep their static paths ──

def only_lists(f):
    if f:
        return [1, 2]
    return [3, 4, 5]


def only_strs(f):
    if f:
        return "ab"
    return "cdef"


def uniform():
    p = only_lists(True)
    q = only_strs(False)
    print(p, len(p), p[0])
    print(q, len(q))


# ── Rebinding one slot across kinds, and a loop that would leak every pass ──

def rebound():
    v = pick(True)
    print(v, len(v))
    v = pick(False)
    print(v, len(v))
    v = pick3(1)
    print(v, len(v))


def in_loop():
    i = 0
    total = 0
    while i < 30:
        v = pick3(i % 3)
        total = total + len(v)
        i = i + 1
    print(total)


pairings()
maybe()
unclassifiable()
uniform()
rebound()
in_loop()
