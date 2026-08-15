"""A conditional expression with an int arm and a float arm keeps both kinds.

BUG-IFEXP-INT-FLOAT-PROMOTE and BUG-VAR-RETYPED-MIDSCOPE-STALE-SLOT.

`_emit_ifexp` decides whether the two arms need a tagged `FpyValue` phi by
asking whether their static kinds agree, and it used to carve out one
exemption:

    # int/float can be promoted to double without fpy_val
    if not ({_body_k, _else_k} <= {VKind.INT, VKind.FLOAT}):
        needs_fv_output = True

The premise is true and the conclusion does not follow.  A `double` really
does hold both an i64-ranged int and a float, which is why this never
produced a bit-reinterpretation — but a conditional expression evaluates to
*whichever arm ran*, unconverted, and promoting erases that:

    print(1 if c else 2.5)      # 1 in CPython; printed 1.0

So the arms disagree and the value carries a tag, like every other
disagreeing pair.

Fixing that exposed a second, older bug underneath, and the two have to be
fixed together because the first is unobservable without the second.

`_returns_mix_int_and_float` used to read return kinds straight off the AST
one expression at a time.  That is enough for `return 1` beside
`return 2.5`, but not for `return 1 if c else 2.5` (one return, two kinds)
and not at all for `v = 1 if c else 2.5; return v` (the kinds are a
property of the local, not of the `return`).  It now runs a small monotone
fixpoint, `_local_scalar_kinds`, over the function's plain assignments —
a fixpoint rather than a single pass because an accumulator needs its own
kinds on the right-hand side:

    t = 0                       # {"int"}
    t = t + (1 if c else 0.5)   # {"int"} on round one, {"int","float"} on two

Anything it cannot classify — a parameter, a `for` target, a call to a
user function — is `None`, "no constraint", never a conflict, so a single
unrecognised assignment cannot push a whole function off the bare ABI.

── The stale slot ──

BUG-VAR-RETYPED-MIDSCOPE-STALE-SLOT.  A local's storage class is decided by
its *first* store.  When a later store needed a wider `fpy_val`, the store
path allocated a *second* alloca and abandoned the first:

    %"t" = alloca double
    %"t.2" = alloca {i32, i64}

Loads emitted before the widening stay bound to the dead slot forever, so
in a loop the accumulator re-read its initial value on every iteration:

    t = 0.0
    i = 0
    while i < 10:
        t = t + (1 if i % 2 else 0.5)   # printed 0.25, not 7.5
        i = i + 1

`_scan_fv_forced_locals` already existed to prevent exactly this — its own
docstring describes the failure — but it was run only over *function*
bodies, and it did not know that an IfExp with disagreeing arms yields a
mixed value.  Both gaps are closed: it now recognises such an IfExp, and
Pass 3 runs it over the module's top-level statements too (excluding names
backed by a real LLVM global, whose storage is not an alloca and cannot be
widened).
"""


# ── The repro ──

c = True
d = False

print(1 if c else 2.5)
print(1 if d else 2.5)
print(2.5 if c else 1)
print(2.5 if d else 1)


# ── Bound to a name first ──

a = 1 if c else 2.5
b = 1 if d else 2.5
print(a, b)
print(a + b)
print(a * 2, b * 2)
print(int(b), float(a))
print(str(a), str(b))
print(f"{a} {b}")
print([a, b])


# ── Returned directly, and by way of a local ──

def direct(x):
    return 1 if x else 2.5


def via_local(x):
    v = 1 if x else 2.5
    return v


def two_hops(x):
    v = 1 if x else 2.5
    w = v
    return w


def nested(x, y):
    return (1 if x else 2.5) if y else (3 if x else 4.5)


print(direct(1), direct(0))
print(via_local(1), via_local(0))
print(two_hops(1), two_hops(0))
print(nested(1, 1), nested(0, 1), nested(1, 0), nested(0, 0))


# ── An arm that is itself tagged ──
# `_ifexp_branch_kind` used to answer `None` — "dynamic, unknown" — for both a
# nested disagreeing ternary and a name of MIXED kind.  Two `None`s look like
# agreement, so the outer ternary skipped the tagged phi and merged two
# FpyValues as naked i64.

e = a if d else b
f = b if c else a
print(e, f)
print((a if c else b) + (a if d else b))
print(1 if c else (2 if c else 3.5))
print((1.5 if c else 2) if d else 3)


# ── Arithmetic on the result, where the int-ness must survive ──

def arith(x):
    return (1 if x else 2) + (0 if x else 0.5)


def same_kind(x):
    return 1 if x else 2


def same_float(x):
    return 1.5 if x else 2.5


print(arith(1), arith(0))
print(same_kind(1), same_kind(0), same_float(1), same_float(0))
print(same_kind(1) + same_kind(0), same_float(1) + same_float(0))


# ── The accumulator: one slot per name, in a function ──

def acc_while():
    t = 0.0
    i = 0
    while i < 10:
        t = t + (1 if i % 2 else 0.5)
        i = i + 1
    return t


def acc_for():
    u = 0
    for j in range(6):
        u = u + (2 if j % 2 else 0.25)
    return u


def acc_int_first():
    t = 0
    i = 0
    while i < 4:
        t = t + (1 if i % 2 else 0.5)
        i = i + 1
    return t


print(acc_while())
print(acc_for())
print(acc_int_first())


# ── ...and at module level, which was never pre-scanned at all ──

mt = 0.0
mi = 0
while mi < 10:
    mt = mt + (1 if mi % 2 else 0.5)
    mi = mi + 1
print(mt)

mu = 0
for mj in range(6):
    mu = mu + (2 if mj % 2 else 0.25)
print(mu)


# ── An IfExp inside a call argument, a container, a comparison ──
# (`abs()` is absent on purpose: it does not handle a tagged argument at all,
#  which is BUG-ABS-OF-TAGGED-VALUE and predates this fix.)

print(max(1 if c else 2.5, 2))
print([1 if c else 2.5, 1 if d else 2.5])
print((1 if c else 2.5) > 2, (1 if d else 2.5) > 2)
print(len([0]) + (1 if c else 2.5))


# ── Unrecognisable operands are "no constraint", not a conflict ──

def helper(x):
    return x * 2


def calls_helper(x):
    if x:
        return helper(3)
    return helper(4)


def param_kinds(p, q):
    return p if q else 1


print(calls_helper(1), calls_helper(0))
print(param_kinds(5, 1), param_kinds(5, 0), param_kinds(2.5, 1))


# ── Bools stay bools ──

def bool_or_float(x):
    return (x > 0) if x else 1.5


print(bool_or_float(1), bool_or_float(0), bool_or_float(-1))
print(True if c else 2.5, True if d else 2.5)


# ── Nested function bodies are not scanned as part of the outer one ──

def outer():
    t = 1

    def inner():
        v = 1 if c else 2.5
        return v

    print(t, inner())
    return t


print(outer())
