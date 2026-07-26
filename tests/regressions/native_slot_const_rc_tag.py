"""A slot holding an FpyValue must be refcounted with the tag *in the value*.

BUG-NATIVE-SLOT-CONST-RC-TAG.

`_retain_native_store` makes a bare (non-FpyValue) alloca own what it holds, and
it retained/released with a tag derived from the variable's **static** kind:

    self.builder.call(self.runtime["rc_incref"],
                      [ir.Constant(i32, fpy_tag), self._ptr_as_i64(value)])

That is right for a genuine native slot — one native pointer whose kind the
compiler knows. But the bare-ABI store path also takes whole `{i32, i64}`
FpyValues, and there the static kind is a guess. A function returning a str on
one branch and a list on another is typed `list`, so:

    def pick(flag):
        if flag:
            return "abcd"
        return [1, 2, 3]

    r = pick(True)          # fpy_rc_incref(FPY_TAG_LIST, <str pointer>)

retained a string through the `FpyList` header offset and wrote past the end of
the allocation — an outright segfault at module scope, before anything printed:

    AddressSanitizer: SEGV ... caused by a WRITE memory access
        #0 fpy_rc_incref runtime/objects.c

The store itself was never wrong. The emitted IR stored the correct struct and
`print(r)` rendered `abcd` through `fastpy_fv_write` on the same variable in the
same statement; only the *refcount* ops flanking the store used a constant:

    %".4" = call {i32, i64} @"fastpy.user.pick"(...)   ; correct runtime tag
    call void @"fpy_rc_incref"(i32 5, i64 %".5")       ; 5 == FPY_TAG_LIST
    store {i32, i64} %".4", {i32, i64}* %"r"           ; correct tag stored

So the fix is not a better static guess — no static tag can be right here, since
the kind depends on the branch taken. The slot is tagged at runtime already;
retain and release now read that tag (`_RC_TAG_DYNAMIC` in the slot registry)
instead of a compile-time constant. The FpyValue-locals store path had always
done this; the bare-ABI path was the hole.

Note this is *not* the `len()` dispatch being wrong. `_emit_builtin_len` already
falls back to `fastpy_fv_len`, which switches on the tag. The crash was in the
assignment. `len()` on a *module-level* mixed-kind variable was separately
broken while this test was written (BUG-MODULE-DOCSTRING-UNBOXES-GLOBAL, since
fixed); `mixed_return_tag.py` covers that side.
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
    return [9]


# ── Module scope: where the original crash landed ──
# The retain happens on the assignment, so binding alone is enough to
# reproduce; the crash was before any of these printed.

r = pick(True)
print(r, len(r))
s = pick(False)
print(s, len(s))
t = pick3(1)
print(t, len(t))


# ── Function scope, and rebinding one slot across kinds ──

def in_func():
    v = pick(True)
    print(v, len(v))
    v = pick(False)
    print(v, len(v))
    v = pick(True)
    print(v, len(v))


# ── Three different kinds through one slot, including a dict ──

def three_kinds():
    a = pick3(0)
    b = pick3(1)
    c = pick3(2)
    print(a, len(a))
    print(b, len(b))
    print(c, len(c))


def rebound_across_three():
    x = pick3(0)
    print(x, len(x))
    x = pick3(1)
    print(x, len(x))
    x = pick3(2)
    print(x, len(x))


# ── A loop alternating kinds: a wrong tag corrupts or leaks every iteration ──

def in_loop():
    i = 0
    total = 0
    while i < 40:
        v = pick(i % 2 == 0)
        total = total + len(v)
        i = i + 1
    print(total)


def in_loop_three():
    i = 0
    total = 0
    while i < 30:
        v = pick3(i % 3)
        total = total + len(v)
        i = i + 1
    print(total)


# ── The value must stay alive after the assignment's temps are flushed ──

def survives_statement_boundary():
    a = pick(True)
    b = pick(False)
    c = pick(True)
    print(a, b, c)
    print(len(a), len(b), len(c))


def aliased():
    a = pick(True)
    b = a
    a = pick(False)
    print(a, b)
    print(len(a), len(b))


# ── A scalar branch: rc_incref must no-op rather than treat an int as a ptr ──

def mixed_with_scalar(n):
    if n == 0:
        return 1234
    if n == 1:
        return "str"
    return [1, 2]


def scalar_branch():
    a = mixed_with_scalar(0)
    b = mixed_with_scalar(1)
    c = mixed_with_scalar(2)
    print(a, b, c)
    print(len(b), len(c))


# ── Uniform-kind functions must be untouched (the static path still works) ──

def always_str(n):
    return "x" * n


def always_list(n):
    return [n, n]


def uniform_unchanged():
    a = always_str(3)
    b = always_list(4)
    print(a, len(a), b, len(b))


in_func()
three_kinds()
rebound_across_three()
in_loop()
in_loop_three()
survives_statement_boundary()
aliased()
scalar_branch()
uniform_unchanged()
