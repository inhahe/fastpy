"""A `bytes` value must keep its kind when it crosses a function return.

BUG-BYTES-RETURN-TAG-LOST.

    def ob():
        return b"abc"

    print(len(ob()))     # 0
    print(ob())          # a pointer, printed as an integer

`str`, `list`, `dict` and `tuple` all had arms in the return-type chain;
`bytes` had none anywhere in it, and `set` had only half of one. Three
separate places had to learn the kind, and each was hiding the next:

* `_csa_propagate_ret_types` never recorded "bytes", so nothing downstream
  could classify a call site that passed one — `blen(ob())` typed its
  parameter from whatever *other* call site happened to be classifiable.
* `_duf_detect_ret_type` had no arm either, so the function was declared
  returning `i64`. Every pointer-gated path then declined to fire: the BYTES
  arm of the subscript emitter is behind `isinstance(obj.type, PointerType)`,
  so `ob()[0]` fell through to the generic CPython `__getitem__` bridge and
  faulted.
* Once the LLVM type was widened to a pointer, `_duf_determine_ret_tag`'s
  pointer arm still had nowhere to land and fell through to its `"ptr"`
  default — which means *list*. `ob() + b"d"` then concatenated as a list and
  printed `()`.

Two consumers of the kind were separately blind to it. `_is_bytes_expr` knew
that a *variable* could hold bytes but not that a *call* could, so
`b = ob(); b + b"d"` worked while `ob() + b"d"` produced a str; it now reads
the declared return tag, and `_infer_type_tag`'s private copy of the same
predicate was deleted in favour of it. And `return v` from an untyped
parameter had STR/DICT/LIST arms but no BYTES/SET one, so `len(echo(ob()))`
measured a bytes object as a list.

`set` is exercised alongside `bytes` throughout because it shared the same
gaps and the same fix.
"""


def ob():
    return b"abc"


def oenc():
    return "hi".encode()


def obc():
    return bytes([65, 66, 67])


def oset():
    return {1, 2, 3}


def osc():
    return set([1, 2, 2, 3])


# ── The repro: length and repr of a returned bytes ──

print(len(ob()), len(oenc()), len(obc()))
print(ob(), oenc(), obc())
print(len(oset()), len(osc()))
print(sorted(oset()), sorted(osc()))


# ── Through an untyped parameter, with no classifiable call site ──

def blen(v):
    return len(v)


def bshow(v):
    print(v)


def echo(v):
    return v


print(blen(ob()), blen(oset()))
bshow(ob())
bshow(oenc())
print(len(echo(ob())), echo(ob()))
print(len(echo(oset())))


# ── A literal call site still types the parameter ──

def blen2(v):
    return len(v)


print(blen2(b"abcd"), blen2(ob()))


# ── Operators: the result of a concat is bytes, not str and not a list ──

print(ob() + b"d")
print(b"d" + ob())
print(ob() * 2)
print(ob() == b"abc", ob() == b"abd")
print(ob() != b"abc")


# ── The same through a variable, which always worked ──

_v = ob()
print(_v + b"d", len(_v), _v[0])


# ── Subscript and slice, which used to reach the CPython bridge ──

print(ob()[0], ob()[-1])
print(ob()[1:], ob()[:2], ob()[::-1])
print(len(ob()[1:]))


# ── Iteration and containment ──

for _c in ob():
    print(_c)

print(65 in obc(), 99 in obc())
print(2 in oset(), 9 in oset())

# `in` on a bytes had no arm in the emitter at all: an int operand is a byte
# value, a bytes operand is a subsequence, and both used to fall through to
# the CPython `__contains__` bridge and fault.  BUG-BYTES-CONTAINS-NO-ARM.
print(97 in b"abc", 100 in b"abc")
try:
    print(256 in b"abc")
except ValueError:
    print("ValueError")
print(b"bc" in b"abc", b"ac" in b"abc", b"" in b"abc", b"abcd" in b"abc")
print(97 not in b"abc", 100 not in b"abc", b"bc" not in b"abc")
print(97 in ob(), b"bc" in ob(), 66 in obc())
_bv = ob()
print(97 in _bv, b"ab" in _bv)
print(0 in b"a\x00b", b"\x00b" in b"a\x00b")


# ── Forward references: the callee is defined after its caller ──

def use_fwd():
    print(len(fwd_bytes()), len(fwd_set()))
    print(fwd_bytes() + b"z")
    print(sorted(fwd_set()))


def fwd_bytes():
    return b"xy"


def fwd_set():
    return {4, 5}


use_fwd()


# ── Inside a function, and accumulated across a loop ──

def in_func():
    x = ob()
    s = oset()
    print(x, len(x), len(s))
    t = 0
    i = 0
    while i < 3:
        t = t + blen(ob())
        i = i + 1
    print(t)
    out = b""
    j = 0
    while j < 3:
        out = out + ob()
        j = j + 1
    print(out, len(out))


in_func()


# ── An annotation is still evidence; the typed paths must not move ──

def ann_b(b: bytes) -> bytes:
    return b + b"!"


def ann_s(s: str) -> str:
    return s + "!"


print(ann_b(b"q"), ann_s("q"))


# ── str must keep behaving exactly as before ──

def ostr():
    return "abc"


print(len(ostr()), ostr(), ostr() + "d", ostr()[0], ostr()[1:])
print(blen(ostr()), echo(ostr()))
