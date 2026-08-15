"""A call's return kind comes from the callee, not from the call's arguments.

BUG-CALL-ARG-TYPE-GUESSES-FLOAT-FROM-ARGS.

`_infer_call_arg_type` types the argument expressions of a call so the right
specialization of the *callee* is picked.  For `g(f(a, 1.5))` it has to answer
"what kind does `f(a, 1.5)` produce".  It consulted `f`'s `ret_tag` and named
four kinds — float, int, bool, str — then **fell through** to a last-resort
heuristic that walks the whole expression for a float literal:

    has_float = any(isinstance(sub, ast.Constant) and isinstance(sub.value, float)
                    for sub in ast.walk(node))

On a Call node that walk reaches the *arguments*.  So `f(a, 1.5)` was typed
float purely because `1.5` appears inside it, even when `f` returns an index.

That fall-through was unreachable while every such function returned a bare
i64 (`ret_tag == "int"` answers on the line above).  Once
BUG-BIGINT-RETURNED-FROM-FUNCTION-LOSES-TAG made a BigInt-capable function
return `"mixed"`, the fall-through opened: `g` was specialised on a `double`
parameter and the returned FpyValue — correctly tagged INT — was converted to
a double on the way in.  `bisect_right([1, 2], 1.5)` then compared `1.0`
against the expected `1`, and 14 of test_bisect's 2857 assertions failed
while printing "got 1 expected 1".

The fix is that the callee's own `ret_tag` is authoritative: a kind the table
has no name for ("mixed", a container, void) means *unknown*, which is a
`None` the specialization scorer already handles — not a licence to guess
from syntax.
"""


def idx(a, x):
    """The bisect shape: returns an int, takes a possibly-float `x`."""
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


def show(actual, expected):
    print(actual, type(actual), actual == expected)


# ── The reported repro: the call result is an argument, and the call's own
# ── argument is a float literal.

show(idx([1, 2], 1), 1)
show(idx([1, 2], 1.5), 1)
show(idx([1, 2, 3], 2.5), 2)
show(idx([1, 2, 2, 3, 3, 3, 4, 4, 4, 4], 3.5), 6)


# ── Storing first must agree with passing directly ──

v = idx([1, 2], 1.5)
print(v, type(v), v == 1)


# ── A float literal buried deeper in the call must not leak out either ──

def pick(a, x, k):
    return idx(a, x) + k


show(pick([1, 2, 3], 2.5, 0), 2)
print(pick([1, 2, 3], 2.5, 1), pick([1, 2, 3], 2, 1))


# ── A genuinely float-returning callee must still be typed float ──

def half(x):
    return x / 2


show(half(5), 2.5)
show(half(4.0), 2.0)
print(half(5) + 1, half(5) * 2)


# ── …and a float-typed *expression* argument, which is what the
# ── fall-through is actually for, must keep working.

def take(x):
    return x * 2


print(take(1.5), take(1 + 0.5), take(3))
print(take(1.5) == 3.0, take(3) == 6)


# ── The same shape with a BigInt in the program, which is what turned the
# ── callee's ret_tag into "mixed" in the first place.

big = 2 ** 80
print(big)
show(idx([1, 2], 1.5), 1)
show(idx([1, 2], 1), 1)
print(idx([1, 2], 1.5) + idx([1, 2], 1))


# ── Nested: the result of a mixed-returning call is the argument to another ──

def twice(n):
    return n * 2


print(twice(idx([1, 2, 3], 2.5)))
print(twice(idx([1, 2, 3], 2)))
print(twice(idx([1, 2, 3], 2.5)) == 4)
