"""A list literal passed to a function keeps its element kind.

BUG-BIGINT-COMPARES-BY-POINTER, the parameter half.

The CSA call-site scan classified an `ast.List` argument by hand, looking
at the *first* element and recognising exactly four shapes: a nested list
(`list:list`), a tuple (`list:tuple`), a str constant (`list:str`), and a
`_csa_list_is_mixed` verdict (`list:mixed`).  Everything else fell to a
bare `"list"`, which carries no element type — and the consumer fills that
in with `VKind.INT`.  So a BigInt element was compared by address:

    def pick(vs):
        return vs[0]

    big = 2 ** 85
    pick([big]) == big          # was False, CPython says True

and a float element was read as its own bit pattern:

    def add_one(fs):
        return fs[0] + 1

    add_one([1.5, 2.5])         # was 4609434218613702657, CPython says 2.5

4609434218613702657 is 0x3FF8000000000000 + 1 — the IEEE-754 bits of 1.5
loaded as an i64.  Nothing crashed and nothing printed oddly; the answers
were simply false, which is why this hid for so long.

`str` elements worked all along, because `list:str` was one of the four
hand-recognised shapes.  That asymmetry — the identical program correct
for strs and wrong for floats — is the tell that this was the *argument
classifier* rather than the container or the callee.

The hand-rolled arm is now gone in favour of `_csa_list_elem_tag`, the
same classifier the return-tag path uses, so a call-site list literal is
typed by exactly the rules a returned one is.  It answers for every
element kind it can name, says `"mixed"` when the elements are all
classified but disagree, and declines to the old bare `"list"` when it
genuinely does not know.

Every section below reads an element back out inside the callee in a way
that depends on the element's *tag* rather than its bits.
"""


# ── BigInt elements: the original report ─────────────────────────────────

def pick(vs):
    return vs[0]


big85 = 2 ** 85

print(pick([big85]) == big85)
print(pick([2 ** 85]) == big85)
print(pick([2 ** 90, 2 ** 91]) == 2 ** 90)
print(pick([big85]))

xs = [big85]
print(pick(xs) == big85)


# ── float elements: arithmetic reads the tag, not just the bits ──────────

def add_one(fs):
    return fs[0] + 1


def second(fs):
    return fs[1]


print(add_one([1.5, 2.5]))
print(second([1.5, 2.5]), second([1.5, 2.5]) * 2)
print(add_one([0.25]))


# ── str elements: the shape that already worked ──────────────────────────

def first_len(ws):
    return len(ws[0])


def shout(ws):
    return ws[0].upper() + "!"


print(first_len(["alpha", "b"]))
print(shout(["alpha"]))
print(pick(["alpha", "beta"]) == "alpha")


# ── int elements must be unchanged ───────────────────────────────────────

def total(ns):
    return ns[0] + ns[1]


print(total([1, 2]), pick([7, 8]), first_len([[1, 2, 3]]))
print(pick([1, 2]) == 1)


# ── bool elements ────────────────────────────────────────────────────────

def flip(bs):
    return not bs[0]


print(flip([True]), flip([False]), pick([True, False]))


# ── bytes elements ───────────────────────────────────────────────────────

def blen(bs):
    return len(bs[0])


print(blen([b"abc", b"de"]))


# ── Nested lists and tuples: the shapes that already worked ──────────────

def inner_first(rows):
    return rows[0][0]


def inner_len(rows):
    return len(rows[0])


print(inner_first([[1, 2], [3]]), inner_len([[1, 2], [3]]))
print(inner_first([["a", "bb"]]))
print(pick([(1, 2), (3, 4)]))
# `len(inner_first([["a", "bb"]]))` still answers 0: a nested list literal
# argument is tagged "list:list", which records that the elements are lists
# but not that *theirs* are strs.  BUG-NESTED-LIST-ARG-INNER-ELEM-LOST.


# ── dict elements ────────────────────────────────────────────────────────

def get_a(ds):
    return ds[0]["a"]


print(get_a([{"a": 1}, {"a": 2}]))
# `len(get_a([{"a": "x"}]))` still answers 0 — a list-of-dicts parameter keeps
# no dict *value* type, so `ds[0]["a"]` reads a str pointer as an int.  It
# segfaulted before this fix and now merely answers wrongly.
# BUG-LIST-OF-DICTS-PARAM-VALUE-KIND-LOST.


# ── Comprehension arguments take the same path as a literal ──────────────

def sum_all(ns):
    t = 0
    for n in ns:
        t = t + n
    return t


print(sum_all([i * 2 for i in range(4)]))
print(add_one([i / 2 for i in range(3)]))
print(first_len([str(i) + "x" for i in range(2)]))


# ── Declining is correct: mixed and empty stay untyped ───────────────────

def count(vs):
    return len(vs)


print(count([]), count([1, "a"]), count([1, 2, 3]))
print(pick([1, "a"]))


# ── Disagreeing is knowledge; not knowing is not ──────────────────────────
# Every element classified but *differing* says so, as "mixed", which routes
# the read through the per-element runtime tag rather than defaulting to int.

def show_two(vs):
    return vs[0], vs[1]


print(show_two([2 ** 85, "s"]))
print(pick([2 ** 85, "s"]) == big85)


# ── Two call sites that disagree must not corrupt each other ─────────────

def echo(vs):
    return vs[0]


print(echo([1.5]), echo(["a"]), echo([2 ** 85]) == big85, echo([3]))


# ── The tag survives the callee's own operations ─────────────────────────

def biggest(vs):
    m = vs[0]
    for v in vs:
        if v > m:
            m = v
    return m


print(biggest([1.5, 3.25, 2.0]))
print(biggest(["a", "c", "b"]))
# `biggest([2 ** 85, 2 ** 86]) == 2 ** 86` still answers False: the loop-carried
# `m` loses the BIGINT kind across the `if v > m` rebinding, which is a
# different reader from the subscript this test covers.
# BUG-LOOP-CARRIED-BIGINT-KIND-LOST.
print("end")
