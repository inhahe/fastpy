"""A function returning an int on one path and a float on another keeps its tag.

BUG-MIXED-SCALAR-RETURN-TAG.

The bare ABI returns a naked i64 or a naked double — whichever the return-type
detector guessed — and has nowhere to put a runtime tag.  For a function whose
returns genuinely disagree, whichever of the two is chosen, the other kind's
bits travel back reinterpreted:

    def int_or_float(f):
        if f:
            return 1
        return 2.5
    print(int_or_float(True), int_or_float(False))

printed `1 4612811918334230528` — the IEEE-754 bits of 2.5 read as an i64.
Assigning the results first (`a = int_or_float(True)`) failed the other way
round, `5e-324 2.5`, because the module-level variable was typed from the
function's single guessed return type.

`_csa_returns_disagree` had already made this move for *pointer* returns and
explicitly declined to make it for scalars, on the grounds that "int/float
returns are settled by a separate mechanism (the i64 vs double LLVM return
type)".  They are not settled by it; that mechanism is precisely the one that
picks one and discards the other.  `_returns_mix_int_and_float` is the scalar
counterpart, and like `_CSA_LITERAL_PTR_KIND` it is deliberately narrow —
anything it cannot read off the AST counts as "no constraint", never as a
conflict, so a single `return helper()` cannot push a whole function off the
bare ABI.

Three consumers had to agree, the same way the splat fix needed three:

* `_duf_select_abi` denies such a function the bare ABI, so the FpyValue can
  carry the tag at all;
* `_duf_determine_ret_tag` records `"mixed"`, so callers do not unwrap the
  returned FpyValue by a static guess;
* `_csa_propagate_ret_types` records `"mixed"` too, so a module-level
  `a = f(...)` is not typed from the guess either.

Two details the first attempt got wrong:

* **A bool return is not an int return.** `return True` beside `return -1.5`
  reached `_emit_return`'s promote path, which tagged every integer INT, so
  the compiled program printed `1` where CPython prints `True`.  The check has
  to run *before* the `_is_float_expr` one, because that answers yes for
  `x > 5` when `x` is float-typed — but a comparison is a bool whatever it
  compares.

* **A `-> float` annotation is not a promise.** Python does not enforce it, so
  `def a(x) -> float: return 1` really does return the integer 1.  Letting the
  annotation win produced neither answer: the tag said float, the value was an
  i64, and the caller printed 4612811918334230528.  The `"mixed"` override
  therefore runs *after* the annotation override, not before it.
"""


def int_or_float(f):
    if f:
        return 1
    return 2.5


def bool_or_float(x):
    if x > 0:
        return True
    return -1.5


def cmp_or_float(x):
    if x > 0:
        return x > 5
    return -1.5


def not_or_float(x):
    if x > 0:
        return not x
    return 1.25


def boolop_or_float(x):
    if x > 0:
        return x > 1 and x < 5
    return 1.25


def safe_div(a, b):
    if b == 0:
        return 0
    return a / b


def neg(x):
    if x:
        return -3
    return -0.5


def powers(x):
    if x:
        return 2 ** 3
    return 2 ** -1


def annotated(x) -> float:
    if x:
        return 1
    return 2.5


def annotated_int(x) -> int:
    if x:
        return 1
    return 2.5


def recurse(n):
    if n <= 0:
        return 0
    return 0.5 + recurse(n - 1)


def mean(v):
    if len(v) == 0:
        return 0
    t = 0.0
    for x in v:
        t = t + x
    return t / len(v)


def parity(i):
    if i % 2 == 0:
        return 2
    return 0.25


# ── The repro ──

print(int_or_float(True), int_or_float(False))

a = int_or_float(True)
b = int_or_float(False)
print(a, b)
print(a + b)


# ── Bools must stay bools ──

print(bool_or_float(1), bool_or_float(-1))
print(cmp_or_float(1), cmp_or_float(9), cmp_or_float(-1))
print(not_or_float(1), not_or_float(0), not_or_float(-1))
print(boolop_or_float(3), boolop_or_float(9), boolop_or_float(-1))


# ── Division, negation, powers ──

print(safe_div(7, 2), safe_div(7, 0), safe_div(9, 3))
print(neg(1), neg(0))
print(powers(1), powers(0))


# ── An annotation is not enforced by CPython either ──

print(annotated(1), annotated(0))
print(annotated_int(1), annotated_int(0))


# ── Recursion and a classic "empty means 0" accumulator ──

print(recurse(0), recurse(1), recurse(4))
print(mean([]), mean([1, 2, 3]), mean([2, 4]))


# ── The result used in arithmetic, formatting and containers ──

print(parity(0) + parity(1), parity(0) * 2, parity(1) * 2)
print(int(parity(0)), float(parity(1)))
print(str(parity(0)), str(parity(1)))
print(f"{parity(0)} {parity(1)}")
print([parity(0), parity(1)])


# ── Inside a function, accumulated in a loop ──

def inner():
    t = 0.0
    i = 0
    while i < 10:
        t = t + parity(i)
        i = i + 1
    print(t)
    u = 0
    for j in range(6):
        u = u + parity(j)
    print(u)


inner()


# ── A function whose returns do *not* disagree keeps its old typing ──

def all_int(x):
    if x:
        return 1
    return 2


def all_float(x):
    if x:
        return 1.5
    return 2.5


print(all_int(1), all_int(0), all_float(1), all_float(0))
print(all_int(1) + all_int(0), all_float(1) + all_float(0))
