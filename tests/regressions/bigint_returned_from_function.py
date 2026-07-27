"""A BigInt returned through a call must keep its tag.

BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG.

Return-type inference typed a BigInt-producing return as a plain scalar or as
a bare pointer, so the caller narrowed the FpyValue to its `data` field — which
for a BIGINT *is* the pointer.  `neg(b) + b` printed `2**80` plus a heap
address, and the number changed run to run.

Three separate holes, all in how a return is typed:

* **`return <param>` where the param is a BigInt** landed in the i8_ptr branch
  of the ret_tag inference, whose default is `"ptr"` — which means *list*.
  Hence `TypeError: unsupported operand type(s) for +: 'list' and 'int'`.
  Guessing list for an unrecognised pointer is the worst available default,
  because every pointer fits it.  That branch never grew the
  `returns_untyped_param -> "mixed"` arm the i64 branch has had since
  BUG-RETURNS-UNTYPED-PARAM-RET-TAG.

* **`return -x` / `return x * 2`** were typed `int`/i64.  That is the right
  *width* but the wrong claim: in a program that can promote, those operators
  go through `fpy_checked_*`, whose result may be a BIGINT-tagged FpyValue.

* **The ABI has to agree.**  Saying `"mixed"` is only half the answer — the
  bare ABI has nowhere to put a tag, so `_duf_select_abi` must also deny it,
  exactly as it already does for a function returning int on one path and
  float on another.

Naming the kind statically (`ret_tag = "bigint"`) was tried and only moved the
error: a bare call expression's kind is guessed from the LLVM return type,
which is i8* for BigInt, Decimal *and* str alike, so the complaint changed from
'list' to 'str'.  The FV ABI already carries the real tag, and
`fastpy_fv_binop` / `fastpy_fv_compare` read it correctly, so "mixed" is the
answer that does not need a new arm in every consumer.

Note that assigning first always worked — `v = f(b); v + 0` was correct
throughout — because the *store* path consults a different, correct analysis.
That divergence is the recurring shape here; see BUG-DIRECT-CALL-LEN-STATIC-TAG.
"""

b = 2 ** 80
c = 2 ** 80


def ident(x):
    return x


def neg(x):
    return -x


def dbl(x):
    return x * 2


def addk(x, k):
    return x + k


def acc(n):
    r = 1
    i = 0
    while i < n:
        r = r * (2 ** 80)
        i = i + 1
    return r


# ── The reported repro: consuming the result without storing it first ──

print(neg(b) + b)
print(ident(b) + 0)
print(dbl(b) + 0)


# ── Every return shape, consumed directly ──

print(ident(b))
print(neg(b))
print(dbl(b))
print(addk(b, 1))
print(acc(2))


# ── …and compared, which is the other consumer that reads `data` ──

print(ident(b) == b, ident(b) != b)
print(neg(b) == -b, neg(b) < b, neg(b) > b)
print(dbl(b) == b + b, dbl(b) > b)
print(acc(2) == b * b, acc(1) == b)


# ── Storing first must keep working; it was the path that was already right ──

v = ident(b)
w = neg(b)
print(v + 0, w + b, v == b, w == -b)


# ── Arithmetic chained on a returned BigInt ──

print(ident(b) + ident(c))
print(neg(b) + ident(c))
print(dbl(b) // 2 == b)
print(acc(2) // b == b)
print(-neg(b) == b)
print(abs(neg(b)) == b)


# ── Nested calls: the result of one call is the argument to the next ──

print(ident(ident(b)) == b)
print(neg(neg(b)) == b)
print(ident(neg(b)) + b)


# ── The same functions on ordinary ints must not regress ──
# These take the widened return path too, since the tag is decided per
# function, not per call site.

print(ident(5), neg(5), dbl(5), addk(5, 6))
print(ident(5) + 1, neg(5) + 1, dbl(5) * 2)
print(ident(5) == 5, neg(5) < 0, dbl(5) > 9)
print(ident(2.5), neg(2.5), dbl(2.5))
print(ident("s"), ident([1, 2]), ident(True))


# ── A function whose returns are all plain must stay plain ──

def plain(n):
    t = 0
    i = 0
    while i < n:
        t = t + i
        i = i + 1
    return t


print(plain(10), plain(100))
print(plain(10) + 1, plain(10) == 45)


# ── Through a list, so the value crosses a container boundary too ──

xs = [ident(5), dbl(5), plain(4)]
print(xs, len(xs), xs[0] + xs[1])
