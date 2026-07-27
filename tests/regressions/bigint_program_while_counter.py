"""A big-integer constant anywhere must not hang every `while` counter.

BUG-BIGINT-PROGRAM-HANGS-WHILE-COUNTER.

Pass 0.9 sets `_program_uses_bigint` for the *whole program* when the AST
contains an integer constant >= 1 << 62, a `**` with a constant exponent > 30,
or a `<<` with a constant shift >= 40.  With that flag set, `_emit_int_binop`
stops emitting a plain `add` and routes every integer `+ - * ** <<` through
`fpy_checked_*`, whose result is a *tagged* FpyValue carrying FPY_TAG_BIGINT on
overflow.

`_scan_fv_forced_locals` did not know that.  Its BinOp case asked only whether
an operand was already mixed, and for `i + 1` neither is — so `i` was not
forced wide, took an i64 slot from `i = 0`, and then widened mid-loop into a
*second* alloca:

    %"i.3" = alloca {i32, i64}      ; the wide slot the body writes
    %"i"   = alloca i64             ; the abandoned slot the condition reads

The condition read a slot nobody stored to again, so the counter stayed 0 and
the loop never terminated — no output, no error, no exit.  That is
BUG-SECOND-ALLOCA-NOT-DIAGNOSED firing, and the fix is to let the *operator*
decide, not the operands.

Three qualifiers in the original report were all wrong, so each is pinned here:
the constant's scope is irrelevant (it hangs with the constant inside the same
function); a `while` at *module* scope is unaffected, because a module-level
name is backed by an LLVM global with one fixed storage location; and a `for`
loop is unaffected, because its induction variable's slot is made by the loop
emitter rather than by a first plain store.
"""

# ── The repro: a big constant inside the very same function ──

def f_const_local():
    x = 4611686018427387904          # exactly the 1 << 62 threshold
    i = 0
    while i < 1:
        i = i + 1
    print(i, x)


f_const_local()


# ── The constant at module scope, the loop in a function ──

z = 2 ** 80


def f_const_module():
    i = 0
    while i < 5:
        i = i + 1
    print(i)


f_const_module()


# ── Each of Pass 0.9's three triggers, since they are independent ──

def counter(n):
    i = 0
    while i < n:
        i = i + 1
    return i


print(counter(3), counter(0), counter(1))

lit_trigger = 4611686018427387904    # >= 1 << 62
pow_trigger = 2 ** 31                # exponent > 30
shl_trigger = 1 << 40                # shift >= 40
print(counter(4))


# ── Counters that step by something other than 1, and downward ──

def f_step():
    i = 0
    while i < 10:
        i = i + 3
    print(i)
    j = 10
    while j > 0:
        j = j - 4
    print(j)
    k = 1
    while k < 100:
        k = k * 3
    print(k)


f_step()


# ── Nested loops: the inner counter is re-initialised each pass ──

def f_nested():
    tot = 0
    i = 0
    while i < 3:
        j = 0
        while j < 4:
            tot = tot + 1
            j = j + 1
        i = i + 1
    print(tot, i)


f_nested()


# ── `break`, `continue` and `else` all still see a live counter ──

def f_break():
    i = 0
    while i < 10:
        if i == 4:
            break
        i = i + 1
    print(i)


def f_continue():
    i = 0
    seen = 0
    while i < 6:
        i = i + 1
        if i == 3:
            continue
        seen = seen + 1
    print(i, seen)


def f_while_else():
    i = 0
    while i < 3:
        i = i + 1
    else:
        print("else", i)


f_break()
f_continue()
f_while_else()


# ── An accumulator that genuinely does overflow still promotes ──
# The wide slot is not merely harmless here, it is required: `t` really does
# become a BigInt part-way through the loop.

def f_promotes():
    t = 1
    i = 0
    while i < 70:
        t = t * 2
        i = i + 1
    print(t)


f_promotes()
# `t = t * i` — an accumulator times a *variable* rather than a constant — is
# absent on purpose: it mis-tags the promoted BigInt as a FLOAT and prints
# 6.7e+17.  That is BUG-BIGINT-MUL-BY-VAR-MISTAGS-FLOAT; it predates this fix,
# it fails identically at module scope and in a `for` loop (neither of which
# goes through the slot scan), and it has nothing to do with the hang.


# ── Float arithmetic in the same program is untouched ──
# The scan over-approximates and widens these too; that must stay invisible.

def f_float():
    t = 0.0
    i = 0
    while i < 4:
        t = t + 1.5
        i = i + 1
    print(t, i)


f_float()


# ── The two shapes that were already safe, kept as guards ──

mi = 0
while mi < 3:                        # module scope: backed by a global
    mi = mi + 1
print(mi)


def f_for():
    tot = 0
    for i in range(5):               # slot made by the loop emitter
        tot = tot + i
    print(tot)


f_for()


# ── `+` on something that is not an int at all ──
# The fix keys off the *operator*, so it has to be told that `_emit_int_binop`
# is only reached for integers.  A first cut was not, and widened `v3` in
# `v3 = v1 + v2` into a tagged slot, where the object's `__str__` was never
# found and `f"{v3}"` printed the empty string.  Strings and lists concatenate
# with the same `+` and were at the same risk.

class Vec:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vec(self.x + other.x, self.y + other.y)

    def __str__(self):
        return "Vec(" + str(self.x) + ", " + str(self.y) + ")"


def f_obj_add():
    v1 = Vec(1, 2)
    v2 = Vec(3, 4)
    v3 = v1 + v2
    print(v3)
    print(f"{v3}")
    s1 = "he"
    s2 = "llo"
    s3 = s1 + s2
    print(s3, s3 * 2)
    a = [1, 2]
    b = [3]
    c = a + b
    print(c)
    t = 0.5
    u = t + 1.5                      # a double, never a tagged value
    print(u)


f_obj_add()


# ── A counter that is a parameter, and one that survives a call ──

def f_param(i):
    while i < 7:
        i = i + 1
    return i


def side():
    return 1


def f_call_in_body():
    i = 0
    while i < 4:
        i = i + side()
    print(i)


print(f_param(0), f_param(7))
f_call_in_body()
