"""A nested `def`'s return value must keep its runtime type tag.

BUG-INDIRECT-CALL-RET-TAG-INT.

A nested function is lowered to a closure object and invoked indirectly through
`fastpy_call_ptrN`, which returns a bare `i64`. The call site used to wrap that
`i64` into an `FpyValue` with a hardcoded tag of `0` (INT), so any non-int
return came back as an integer:

    def outer():
        def make(n):
            s = str(n) + "?"
            return s
        r = make(3)
        print(r)        # printed e.g. 88098369175608 instead of 3?

It needed *both* a nested def and binding the result to a name — a direct
`print(make(3))` happened to recover the tag another way, and a module-level
`def` is called directly rather than through a closure object. That is why it
survived so long: the obvious spellings all worked.

A *static* return tag cannot fix this. `FuncInfo.ret_tag` is left at `"int"`
for FpyValue-ABI functions because their real tag travels inside the returned
`{i32, i64}` struct, and a function may return different kinds on different
branches regardless. The tag has to come from the runtime: the `__i64_wrap`
thunk already calls `set_ret_tag` before it discards the struct, so the call
site reads it back with `get_ret_tag()`.

The recovery is deliberately narrow — only for callees that are known
FpyValue-ABI user functions, i.e. the ones that actually go through that thunk.
Lambdas, decorator-returned closures and function-pointer parameters keep the
plain `i64` path, where `fpy_ret_tag` would hold a stale value from some
earlier call. Decorated names are excluded for a second reason: `f` in
`@deco def f(...)` is bound to the decorator's *wrapper*, not to the function
`_user_functions["f"]` describes (BUG-DECORATOR-WRAPPER-STATIC-RET-TAG). The
lambda/decorator cases below are here to prove that path did not regress.

Lambdas needed a change of their own. They returned `i64` in silence, and
silence is not "assume int" — call sites that already used `get_ret_tag()` read
whatever an earlier, unrelated call left behind. A str-returning nested def
anywhere before a lambda call was enough to make `print(f(1))` interpret an int
as a `char*` and segfault. `_emit_lambda_body` now publishes a tag like every
other indirectly-callable body.

Note on naming: every nested helper here has a globally unique name. Two
sibling nested `def`s that share a bare name can silently resolve to one
another (BUG-NESTED-DEF-NAME-COLLISION) — an unrelated bug with its own
regression test. Reusing `make`/`build` across these cases would test that bug
instead of this one.
"""


def str_return():
    def make_str(n):
        s = str(n) + "?"
        return s
    r = make_str(3)
    print(r)
    print(make_str(4))      # direct-print form always worked
    q = make_str(5)
    print(q, len(q), q[0])


def str_return_no_local():
    def make_str2(n):
        return str(n) + "!"
    r = make_str2(6)
    print(r, len(r))


def list_return():
    def build_list(n):
        return [n, n + 1, n + 2]
    a = build_list(10)
    print(a, len(a), a[0], a[2])


def dict_return():
    def build_dict(k):
        return {k: str(k) + "v"}
    d = build_dict("x")
    print(d["x"], len(d))


def float_return():
    def half(n):
        return n / 2
    f = half(7)
    print(f)


def bool_return():
    def gt(a, b):
        return a > b
    t = gt(3, 1)
    u = gt(1, 3)
    print(t, u)


def int_return_unchanged():
    # The common case must be untouched: still a plain int, still usable in
    # arithmetic without an unwrap.
    def twice(n):
        return n * 2
    v = twice(21)
    print(v, v + 1, v * 2)


def none_return():
    def nothing(n):
        if n > 0:
            return None
        return None
    x = nothing(1)
    print(x)


def mixed_branches():
    # The reason a static tag can't work: the kind depends on the branch.
    def pick(n):
        if n > 0:
            return str(n) + "+"
        return str(-n) + "-"
    a = pick(2)
    b = pick(-3)
    print(a, b)


def reassigned_slot():
    # The result slot is rebound across kinds, so the store path has to track
    # what each assignment retained (see BUG-BARE-ABI-STORE-NO-RETAIN).
    def make_tagged(n):
        return str(n) + "s"

    def make_num(n):
        return n * 3

    x = make_tagged(1)
    print(x)
    x = make_num(2)
    print(x)
    x = make_tagged(3)
    print(x)


def in_loop():
    # 100 indirect calls returning fresh strings: a lost tag prints numbers,
    # a lost reference crashes or prints garbage.
    def make_hash(n):
        return str(n) + "#"
    total = 0
    i = 0
    while i < 100:
        s = make_hash(i)
        total = total + len(s)
        i = i + 1
    print(total)


def with_capture():
    # Capturing closures take a different lowering path than the zero-capture
    # one above; both must keep the tag.
    suffix = "-end"

    def make_suffixed(n):
        return str(n) + suffix
    r = make_suffixed(9)
    print(r)


def nested_two_deep():
    def mid(n):
        def innermost(m):
            return str(m) + "i"
        return innermost(n) + "m"
    r = mid(4)
    print(r)


def passed_and_returned():
    def make_p(n):
        return str(n) + "p"
    r = make_p(1)
    t = r
    r = make_p(2)
    print(r, t)


def lambda_unaffected():
    # Lambdas are not FpyValue-ABI; they must keep the plain i64 path.
    f = lambda n: n + 1
    print(f(1), f(10))
    g = lambda a, b: a * b
    print(g(3, 4))


def _identity(fn):
    return fn


@_identity
def _decorated(n):
    return n + 100


def decorator_unaffected():
    print(_decorated(5))


def _shared_wrapper_deco(fn):
    # One `wrapper` body reused for both callees below. It publishes a
    # *statically* inferred return tag, so reading that tag back would give
    # the wrong kind for whichever callee lost the inference coin-flip. This
    # is why a decorated name is excluded from the recovery: `_user_functions`
    # describes the undecorated function, but the variable holds `wrapper`.
    def wrapper(*args):
        return fn(*args)
    return wrapper


@_shared_wrapper_deco
def _deco_int(n):
    return n * 2


@_shared_wrapper_deco
def _deco_str(n):
    return "v" + str(n)


def shared_decorator_wrapper():
    a = _deco_int(4)
    b = _deco_str(4)
    print(a, b)


def sorted_key_unaffected():
    xs = ["bbb", "a", "cc"]
    print(sorted(xs, key=lambda s: len(s)))


str_return()
str_return_no_local()
list_return()
dict_return()
float_return()
bool_return()
int_return_unchanged()
none_return()
mixed_branches()
reassigned_slot()
in_loop()
with_capture()
nested_two_deep()
passed_and_returned()
lambda_unaffected()
decorator_unaffected()
shared_decorator_wrapper()
sorted_key_unaffected()
