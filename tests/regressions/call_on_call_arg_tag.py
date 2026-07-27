"""A call-on-call must publish its argument tags like every other call.

BUG-CALL-ON-CALL-STALE-ARG-TAG.

`C()(7)` cannot be resolved to a known method at compile time — the
callee is whatever `C()` evaluates to — so codegen emits the runtime
name-based dispatcher `fastpy_obj_call_method1(obj, "__call__", 7)`,
whose signature carries only a bare i64.  A callee whose parameter is
UNKNOWN recovers the type from the `fastpy_{set,get}_arg_tag`
side-channel, and that channel is *global and sticky*: it keeps whatever
the last call site wrote.  `_emit_call_on_call` wrote nothing, so
`__call__`'s parameter took the tag of some unrelated earlier argument.

The damage is invisible until something actually reads the tag.  With a
str-tagged leftover, `x * 2` inside `__call__` sees STR and multiplies a
*string* — `fastpy_fv_binop` called `fastpy_str_repeat((char *)7, 2)` and
the process died in `strlen` on address 7.

Every arm of `_emit_call_on_call` had the same hole, `call_ptr1` and
`call_ptr2` (the closure-returning shapes) included, so the test exercises
those too.  The fix is one shared `_emit_set_arg_tags` helper used by all
of them and by the direct-dispatch `__call__` path that already did it by
hand.

The trigger is a *preceding* call that leaves a non-INT tag behind, so
every case below is written as "poison the channel, then call".
"""


# ── The original repro: a str arg poisons slot 0, then C()(7) ───────────

class Greeter:
    def __init__(self, name):
        self.name = name

    def __call__(self):
        return "Hello " + self.name


g = Greeter("World")
print(g())


class Doubler:
    def __call__(self, x):
        return x * 2


print(Doubler()(7))
print(Doubler()(0), Doubler()(-3))


# ── The tag must be the argument's, not the previous call's ────────────
# Each line below is preceded by a call whose slot-0 tag differs from the
# one it needs, so a sticky channel gives a visibly wrong answer.

class Echo:
    def __call__(self, v):
        return v


def poison_str(s):
    return s


def poison_float(f):
    return f


poison_str("abc")
print(Echo()("xyz"))
poison_float(1.5)
print(Echo()(9))
poison_str("abc")
print(Echo()(2.25))
poison_float(1.5)
print(Echo()(True))
poison_str("abc")
print(Echo()([1, 2, 3]))


# ── Two-argument call-on-call ──────────────────────────────────────────

class Pair:
    def __call__(self, a, b):
        return a + b


poison_str("abc")
print(Pair()(3, 4))
poison_str("abc")
print(Pair()("a", "b"))
poison_float(1.5)
print(Pair()(1.25, 2.75))


# ── Closure-returning inner call takes the same path (call_ptr1/2) ─────

def make_adder(n):
    def add(x):
        return x + n
    return add


poison_str("abc")
print(make_adder(10)(5))
poison_float(1.5)
print(make_adder(10)(32))


def make_joiner(sep):
    def join2(a, b):
        return a + sep + b
    return join2


poison_float(1.5)
print(make_joiner("-")("x", "y"))


# ── The arithmetic inside __call__ must stay integer ───────────────────
# A stale FLOAT tag would silently turn these into float results.

class Arith:
    def __call__(self, x):
        return x * 2, x + 1, x - 1, x // 2


poison_float(1.5)
print(Arith()(7))
poison_str("abc")
print(Arith()(10))


# ── Chained and nested call-on-call ────────────────────────────────────

class Counter:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n = self.n + 1
        return self


ctr = Counter()
ctr()()()
print(ctr.n)

poison_str("abc")
print(Doubler()(Doubler()(3)))
