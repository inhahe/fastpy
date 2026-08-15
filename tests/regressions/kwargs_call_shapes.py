"""A `**kwargs` parameter is a dict at every call site, including empty ones.

BUG-EMPTY-KWARGS-CALL-SEGFAULTS.

`def kw(**kwargs): return kwargs` called as `kw()` segfaulted.  The callee's
prologue tags its single parameter `FPY_TAG_DICT` unconditionally, but the
call site built the kwargs dict only `if node.keywords` and otherwise passed
the *positional* list it had also built:

    %".2" = call i8* @"fastpy_list_new"()
    %".3" = call {i32, i64} @"fastpy.user.kw"(i8* %".2")   ; read as a dict

So it was not a null pointer, as first suspected — it was a live `FpyList*`
being read as an `FpyDict*`.  The cause was one arm serving two different
parameters: `*args` (a list) and `**kwargs` (a dict) shared a branch that
chose between them on "were any keywords passed at this call site?", which is
a property of the caller and says nothing about the callee's signature.  They
are separate arms now, and `_emit_kwargs_dict` always materialises a dict.

Both `_emit_user_call` and `_emit_user_call_fv` had their own copy of the
mistake, and of the keyword-packing loop, so the packing moved into
`_emit_kwargs_dict` / `_emit_vararg_list` and all four sites share it.  That
also gave the `**d`-splat case one implementation: a splat whose dict is not a
visible literal survives keyword expansion as a `keyword` with `arg=None`, and
was being handed to `_make_string_constant` as a key name.
"""

# ── The repro ──


def kw(**kwargs):
    return kwargs


print(kw())
print(len(kw()))
print(kw(a=1))
print(sorted(kw(a=1, b=2).items()))
print(sorted(kw(a=1, b=2).keys()))


# ── Every value kind through an empty-then-filled kwargs ──


def kinds(**kwargs):
    out = []
    for k in sorted(kwargs):
        out.append(k + "=" + str(kwargs[k]))
    return ",".join(out)


print(kinds())
print(kinds(i=1, f=2.5, s="x", b=True, n=None))
print(kinds(lst=[1, 2], dct={"z": 1}, tup=(1, 2)))


# ── `*args` and `**kwargs` together, all four fill states ──


# `list(args)` and `type(args).__name__` are deliberately not used here: on a
# `*args` parameter the first returns a tuple and the second says "list".  Both
# are pre-existing and unrelated to kwargs — BUG-TYPE-NAME-OF-TUPLE-SAYS-LIST
# and BUG-LIST-OF-VARARGS-STAYS-A-TUPLE.


def both(*args, **kwargs):
    return len(args), len(kwargs), sum(args), sorted(kwargs)


print(both())
print(both(1, 2))
print(both(x=1))
print(both(1, 2, x=3, y=4))


# ── `*args` alone must still work, filled and empty ──


def va(*args):
    total = 0
    seen = []
    for a in args:
        total = total + a
        seen.append(a)
    return len(args), total, seen


print(va())
print(va(1))
print(va(1, 2, 3))

xs = [1, 2, 3]
print(va(*xs))
print(va(0, *xs))
print(both(*xs, y=1))


# ── `**d` splat: literal, resolvable name, and neither ──


def take(**kwargs):
    return sorted(kwargs.items())


print(take(**{"a": 1, "b": 2}))

lit = {"c": 3}
print(take(**lit))
print(take(d=4, **lit))


def make_kwargs(v):
    out = {}
    out["e"] = v
    return out


print(take(**make_kwargs(5)))
print(sorted(both(**make_kwargs(6))[3]))


# ── Forwarding a kwargs parameter onward, empty and not ──


def inner(**kwargs):
    return sorted(kwargs.items())


def outer(**kwargs):
    return inner(**kwargs)


print(outer())
print(outer(z=9))


# ── The returned dict must behave like a dict ──


def ret(**kwargs):
    return kwargs


e = ret()
print(len(e), sorted(e), "q" in e)
e["late"] = 1
print(sorted(e.items()), e.get("missing", "dflt"))

f = ret(a=1)
f["b"] = 2
print(sorted(f.items()), len(f))


# ── Called in a loop, so an empty call is not merely the first one ──


def acc(**kwargs):
    return len(kwargs)


tot = 0
for i in range(4):
    if i % 2 == 0:
        tot = tot + acc()
    else:
        tot = tot + acc(k=i)
print(tot)
