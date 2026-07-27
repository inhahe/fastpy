"""Subscripting a parameter nothing is known about must dispatch on the tag.

BUG-SUBSCRIPT-UNTYPED-PARAM-BRIDGE.

    def fnv1a(s):
        ...
        c = ord(s[i])      # → fpy_cpython_getattr(s, "__getitem__")

An unannotated parameter whose call sites could not be classified was tagged
`"int"`, so `s` loaded as a naked pointer-as-integer and `s[i]` sailed past the
`fastpy_fv_subscript` runtime-dispatch arm into the generic CPython
`__getitem__` bridge. In pure mode (`-DFPY_PURE_MODE`, SlateOS) those stubs
return NULL and the next use faults; on Windows it is an access violation. The
runtime helper already knew how to index a str, list, dict, tuple or bytes from
the tag — the value simply never reached it.

The cause is the same "silence means scalar" guess that
BUG-UNTYPED-PARAM-BARE-ABI was: `static_param_types` falls back to `i64` when
`param_types` has no evidence, and `_efd_store_parameters` read that fallback
as a real answer. Its *pointer* branch already had an "every caller
unresolvable → mixed" arm; the non-pointer branch did not, and that asymmetry
is the whole bug. An annotation still counts as evidence, so `annotated()`
below keeps the plain typed path.

Two things followed from the parameter becoming `mixed`:

* `return s[0]` is a `mixed` return, so `len(first(...))` gets a tagged value
  instead of an `int` guess — the subscript of an untyped container is itself
  of unknown kind, and saying "int" would only throw the runtime tag away
  again (the shape fixed as BUG-RETURNS-UNTYPED-PARAM-RET-TAG one level up).
* **Slices** had no runtime-dispatch arm at all. `v[1:3]` took whichever static
  path the compiler guessed, and a list arriving on `str_slice` quietly sliced
  to the empty string rather than faulting. `fastpy_fv_slice` picks str/bytes
  or list/tuple from the tag and echoes that tag back, since a slice has the
  same kind as what it came from.

`str` and `list` are exercised through the same parameter throughout, because
the failure mode is precisely that one was being read as the other.
"""


def o_str():
    return "abcdefgh"


def o_list():
    return [10, 20, 30, 40, 50, 60]


def o_dict():
    return {"a": 1, "b": 2}


def o_tuple():
    return (7, 8, 9)


def o_nested():
    return [[1, 2], [3, 4]]


# ── The repro: index an untyped parameter in a loop ──

def fnv1a(s):
    h = 0
    i = 0
    n = len(s)
    while i < n:
        c = ord(s[i])
        h = (h * 31 + c) & 4294967295
        i = i + 1
    return h


print(fnv1a(o_str()))


# ── One index, both kinds, through the same parameter ──

def at(v, i):
    return v[i]


print(at(o_str(), 2), at(o_list(), 2), at(o_tuple(), 2), at(o_nested(), 1))
print(at(o_dict(), "b"))


# ── The result is a value, not just something to print ──

def first(v):
    return v[0]


print(first(o_str()), len(first(o_str())), first(o_list()) + 1)


# ── Negative and computed indices ──

def neg(v):
    return v[-1]


def mid(v):
    return v[len(v) // 2]


print(neg(o_str()), neg(o_list()))
print(mid(o_str()), mid(o_list()))


# ── Nested subscripts ──

def nested(v):
    return v[1][0]


print(nested(o_nested()))


# ── Slices, where a list on the str path used to give "" ──

def sl(v):
    return v[1:3]


def sl_open(v):
    return v[:2]


def sl_neg(v):
    return v[-3:]


def sl_all(v):
    return v[:]


def sl_step(v):
    return v[::2]


def sl_rev(v):
    return v[::-1]


print(sl(o_str()), sl(o_list()))
print(sl_open(o_str()), sl_open(o_list()))
print(sl_neg(o_str()), sl_neg(o_list()))
print(sl_all(o_str()), sl_all(o_list()))
print(sl_step(o_str()), sl_step(o_list()))
print(sl_rev(o_str()), sl_rev(o_list()))
print(len(sl(o_str())), len(sl(o_list())))


# ── Iteration and containment on the same untyped parameter ──

def joinup(v):
    out = ""
    for e in v:
        out = out + str(e)
    return out


def has20(v):
    return 20 in v


print(joinup(o_str()), joinup(o_list()))
print(has20(o_list()))


# ── Mutation through an untyped parameter ──

def bump(v):
    v[0] = 99
    return v[0]


print(bump(o_list()))


# ── An annotation is still evidence; this must keep the typed path ──

def annotated(n: int) -> int:
    return n * 2


def ann_str(s: str) -> str:
    return s[1]


print(annotated(21), ann_str("xyz"))


# ── Nested and closure functions ──

def outer():
    def inner(v):
        return v[1]

    print(inner(o_str()), inner(o_list()))


outer()


# ── The same shapes inside a function and across a loop ──

def in_func():
    print(at(o_str(), 0), at(o_list(), 0))
    print(sl(o_str()), sl(o_list()))
    t = 0
    i = 0
    while i < 12:
        t = t + at(o_list(), i % 6) + ord(at(o_str(), i % 8))
        i = i + 1
    print(t)
    print(fnv1a(o_str()))


in_func()
