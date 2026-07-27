"""A returned list's element kind is a kind, not a yes/no.

BUG-RETURNED-LIST-ELEM-TAG-LOST.

The CSA pre-pass gave a list-returning function one of exactly two tags:
`"ptr:list"` if every element of the returned literal was itself a list,
and the bare `"list"` otherwise.  A bare `"list"` carries no element type,
and the consumer fills that in with `VKind.INT` — so *every* other element
kind was reported to the caller as `int`.  A returned `["alpha", "beta"]`
handed back a list whose elements were string pointers read as integers:
`len()` answered 0, `print()` showed an address, and `.strip()` hung in
the runtime because the pointer was dispatched against whatever class the
stale tag named.

The same list literal written at module scope was correct all along,
which is what made it look like a container bug rather than a return bug:
the element kind is known perfectly well where the list is *written* and
is thrown away by the `return`.

Two sites decided this, and both asked the same yes/no question — the
literal path (`return [...]`) and the refinement for `return <name>`.
Both now ask a classifier for the common element tag, which declines
(leaving the old bare `"list"`) when the elements disagree or there are
none.  The reader had the mirror-image hole: `_get_list_elem_type`'s
user-call arm recognised `"ptr:list"` and nothing else, so a `"list:str"`
would have been ignored even once produced.

The comprehension arm got it wrong in the *other* direction as well.  It
answered "yes, a list of lists" for any element that was an `ast.BinOp`,
on the strength of `[[0] * n for ...]` — so `[i / 2 for i in range(3)]`
also claimed its elements were lists, and `mk_comp_float()[2] + 1` died
with `unsupported operand type(s) for +: 'list' and 'int'` on a float.
Answering the yes/no question wrongly is why the fix could not be just
"fill in the element kind when we know it": the guess had to go.  The
classifier types the arithmetic itself (`int / int` is a float, a
sequence times a count is that sequence) and binds each comprehension's
loop variable to what its iterable yields, so `i` in `for i in range(3)`
is an `int` rather than an unknown name.

Every section below reads an element back out of a returned list in a way
that depends on the element's *tag* rather than its bits: `len()` of a
str, arithmetic on a float, a method call, a nested index.
"""


# ── str elements: the original report ────────────────────────────────────

def mk_const():
    return ["alpha", "beta"]


def mk_local():
    ls = ["alpha", "beta"]
    return ls


lit = ["alpha", "beta"]
print(len(lit[1]), len(mk_const()[1]), len(mk_local()[1]))

for e in mk_const():
    print(len(e), e)

print(mk_const()[1].strip().upper())
print(mk_const()[0] + "!", mk_local()[0][0])
print(sorted(mk_const()), "beta" in mk_const())


# ── float elements: arithmetic reads the tag, not just the bits ──────────

def mk_floats():
    return [1.5, 2.5]


def mk_floats_local():
    fs = [0.25, 0.75]
    return fs


print(mk_floats()[0] + 1, mk_floats()[1] * 2)
print(mk_floats_local()[0], mk_floats_local()[1] + mk_floats_local()[0])
print(sum(mk_floats()))


# ── int elements must be unchanged ───────────────────────────────────────

def mk_ints():
    return [1, 2, 3]


def mk_ints_local():
    xs = [4, 5]
    return xs


print(mk_ints()[0] + 1, mk_ints()[2], len(mk_ints()))
print(mk_ints_local()[0], sum(mk_ints()))


# ── list elements: the one case that already worked ──────────────────────

def mk_nested():
    return [[1, 2], [3]]


def mk_nested_local():
    ns = [[7], [8, 9]]
    return ns


def mk_nested_comp():
    return [[i] for i in range(3)]


print(mk_nested()[0][1], len(mk_nested()[1]), len(mk_nested()))
print(mk_nested_local()[1][0], len(mk_nested_local()))
print(mk_nested_comp()[2][0], len(mk_nested_comp()))


# ── dict elements ────────────────────────────────────────────────────────

def mk_dicts():
    return [{"a": 1}, {"a": 2}]


def mk_dicts_local():
    ds = [{"k": "v"}]
    return ds


print(mk_dicts()[0]["a"], mk_dicts()[1]["a"], len(mk_dicts()))
print(mk_dicts_local()[0]["k"], len(mk_dicts_local()[0]["k"]))


# ── comprehensions, which take the same path as a literal ────────────────

def mk_comp_str():
    return [str(i) for i in range(3)]


def mk_comp_float():
    return [i / 2 for i in range(3)]


def mk_comp_local():
    cs = [str(i) + "x" for i in range(2)]
    return cs


print(len(mk_comp_str()[2]), mk_comp_str()[1])
print(mk_comp_float()[1], mk_comp_float()[2] + 1)
print(len(mk_comp_local()[1]), mk_comp_local()[0])


# ── Arithmetic elements, and the loop variable they read ─────────────────
# `i` is only typeable because the classifier binds it to what `range`
# yields; without that the whole comprehension declines.

def mk_arith_int():
    return [i * 2 + 1 for i in range(4)]


def mk_arith_float():
    return [i * 0.5 for i in range(4)]


def mk_arith_str():
    return [w + "!" for w in ["a", "bb"]]


def mk_arith_bool():
    return [i > 1 for i in range(4)]


def mk_rows():
    # The one shape the old yes/no answer got right, and the reason it
    # answered "list" for every BinOp: a repeated list is still a list.
    return [[0] * 3 for i in range(2)]


print(mk_arith_int()[3] + 1, sum(mk_arith_int()))
print(mk_arith_float()[2] + 1, mk_arith_float()[3])
print(len(mk_arith_str()[1]), mk_arith_str()[0])
print(mk_arith_bool()[0], mk_arith_bool()[3])
print(len(mk_rows()), len(mk_rows()[1]), mk_rows()[0][2])


# ── Declining is correct: mixed and empty stay untyped ───────────────────

def mk_mixed():
    return [1, "a"]


def mk_empty():
    return []


def mk_empty_local():
    e = []
    return e


print(mk_mixed(), len(mk_mixed()))
print(mk_empty(), len(mk_empty()))
print(mk_empty_local(), len(mk_empty_local()))


# ── The tag survives one more hop: assigned, iterated, re-indexed ────────

def mk_words():
    return ["one", "two", "three"]


got = mk_words()
print(len(got[0]), len(got[2]), got[1])
total = 0
for w in mk_words():
    total = total + len(w)
print(total)
joined = ""
for w in mk_words():
    joined = joined + w + "-"
print(joined)


# ── A branchy return still agrees with itself ────────────────────────────

def pick_words(flag):
    if flag:
        return ["yes", "affirmative"]
    return ["no"]


print(len(pick_words(True)[1]), len(pick_words(False)[0]))
print(pick_words(True)[0], pick_words(False)[0])
print("end")
