"""A native (non-FpyValue) variable slot must own the reference it holds.

BUG-BARE-ABI-STORE-NO-RETAIN.

Model-2 refcounting says a producer of a freshly allocated `+1` value
registers it as an *owned temp*, and the whole pending set is released at the
next statement boundary. Anything that wants to keep the value past that
boundary must retain it.

An FpyValue local gets this for free: it is a `{tag, data}` pair, so
`_store_variable`'s FV path can incref the incoming value and decref whatever
the slot held, using the tag that travels with the value.

A *native* slot cannot. Both the `--typed` fast path (`_native_vars`) and the
bare-ABI path store into a bare alloca — an `i8*`, an `i64` — which carries no
runtime tag, so the old code just emitted `builder.store` with no incref at
all. The statement-boundary flush then freed the value out from under the
variable, and the next read returned freed memory:

    def f():
        s = str(7)     # str() registers the +1 as an owned temp
        print(s)       # ...flushed at the end of `s = str(7)` -> freed
                       # `s` still points at it -> garbage / ASan abort

The fix tracks ownership compiler-side instead, in a per-function registry of
`name -> (alloca, tag)`: the store increfs the incoming value, decrefs what
the slot held *using the tag it was retained with*, and `_emit_scope_decref`
releases whatever survives to the function exit.

Two orderings matter and are exercised below:

  * **incref before decref**, so `s = s` (and `s = s[1:]`, `s = f(s)`) cannot
    drop the last reference before taking the new one; and
  * the entry block zeroes the alloca, so a slot assigned only inside an `if`
    is released as NULL — `fpy_rc_decref` returns immediately on `data == 0` —
    rather than decref'ing stack garbage.

Note this only ever *was* observable for producers that actually register an
owned temp. `str()` does; `+` concatenation, f-strings and `.upper()` did not
(they leaked instead). So the coverage below deliberately leans on `str()`,
while also exercising the other producers, which the same store path must
keep correct as they migrate to Model-2.
"""


def simple():
    s = str(7)
    print(s)


def annotated():
    s: str = str(7)
    print(s)


def reassign():
    s = str(7)
    s = str(8)
    s = str(9)
    print(s)


def self_assign():
    # Incref must happen before the decref of the old contents, or this frees
    # the string and then stores the dangling pointer back.
    s = str(41)
    s = s
    t = s
    print(s, t)


def rebind_across_kinds():
    # The slot's release has to use the tag it was *retained* with, not the
    # tag of whatever is being stored now.
    x = str(5)
    print(x)
    x = 12
    print(x)
    x = str(6)
    print(x)
    x = 3.5
    print(x)
    x = str(7)
    print(x)


def conditional_assign(n):
    # `s` is stored on only one path, so the scope-exit release reads the
    # entry-block NULL on the other. Without the zero-init that is a decref of
    # stack garbage.
    if n > 0:
        s = str(n)
        print(s)
    print("end")


def loop_rebind():
    # 300 rebinds of one slot: a missing release leaks without bound, a double
    # release aborts. The value is used after the loop so it must stay live.
    i = 0
    last = ""
    while i < 300:
        last = str(i) + "!"
        i = i + 1
    print(last, len(last))


def other_str_producers():
    a = "x" + "y"
    b = f"<{7}>"
    c = "ab".upper()
    d = ",".join(["p", "q"])
    e = "  z  ".strip()
    print(a, b, c, d, e)


def containers_still_work():
    # LIST/DICT/SET/TUPLE/BYTES slots go through the same store path; they must
    # not be over-released.
    a = [1, 2, 3]
    a = [4, 5]
    d = {"k": str(9)}
    d = {"k": str(10)}
    b = "ab".encode()
    t = (1, 2)
    st = {1, 2, 3}
    print(len(a), a[0], d["k"], len(b), len(t), len(st))


def _make(n):
    return str(n) + "?"


def _make_via_local(n):
    s = str(n) + "?"
    return s


def returned_value_survives():
    # The returned variable is excluded from the scope release — ownership
    # transfers to the caller — so it must still be alive here.
    r = _make(3)
    print(r)
    print(_make(4))
    q = _make_via_local(5)
    print(q)
    # NOTE: `_make` / `_make_via_local` are module-level rather than nested
    # inside this function so that this test exercises one thing — the retain
    # on the store — over the *direct*-call path only. A nested def is lowered
    # to a closure object and called indirectly, which used to drop the result
    # tag (BUG-INDIRECT-CALL-RET-TAG-INT, since fixed); the indirect path is
    # covered by tests/regressions/indirect_call_ret_tag.py.


def param_stays_borrowed(s):
    # Parameters are borrowed from the caller; releasing one here would be a
    # double free at the call site.
    t = s
    print(t, s)


def nested_scopes():
    s = str(1)
    for i in range(3):
        u = str(i) + "-" + s
        print(u)
    print(s)


simple()
annotated()
reassign()
self_assign()
rebind_across_kinds()
conditional_assign(3)
conditional_assign(-1)
loop_rebind()
other_str_producers()
containers_still_work()
returned_value_survives()
param_stays_borrowed(str(77))
nested_scopes()
