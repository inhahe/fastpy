"""A tuple survives being put in a variable before it is returned.

BUG-TUPLE-RETURN-SEGFAULTS.

`return (10, 20)` written directly was always correct: the return-tag
inference lists `ast.Tuple` beside `ast.List` and answers "a pointer,
tagged list", which is right because a tuple is an `FPY_TAG_LIST` at
runtime.  One assignment before the return lost all of that:

    def loc_t():
        q = (10, 20)
        return q

    print(loc_t())          # (10, 20)  — print reads the runtime tag
    print(len(loc_t()))     # 0         — the address measured as a length
    print(loc_t()[0])       # segfault  — the address dereferenced

The scan that records "which local holds what" had arms for `ast.List`,
`ast.ListComp`, `ast.Set`, `ast.SetComp`, `ast.Dict` and `ast.DictComp`
— every container literal except `ast.Tuple`.  So `q` was in no set, the
`return <Name>` arms matched nothing, and the function was given an i64
return.  `print` kept working throughout, because it goes through the
runtime tag rather than the static one, which is exactly what made the
gap easy to miss.

Module-level tuples had the same hole one layer earlier:
`_csa_build_var_types` classified list, dict, set and the scalar
constants, but not `ast.Tuple`, so a global tuple had no recorded kind
for the return inference to find in the first place.
"""


# ── The local-variable form: the one that crashed ────────────────────────

def loc_t():
    q = (10, 20)
    return q


def lit_t():
    return (10, 20)


print(loc_t(), len(loc_t()), loc_t()[0])
print(lit_t(), len(lit_t()), lit_t()[1])


# ── An alias chain, which the same seeding has to survive ────────────────

def two_hops():
    a = ("x", "y", "z")
    b = a
    return b


print(two_hops(), len(two_hops()), two_hops()[2])


# ── Element kinds that are not int, where a wrong tag is visible ─────────

def floats():
    q = (1.5, 2.5)
    return q


def strs():
    q = ("ab", "cd")
    return q


def nested():
    q = ([1, 2], [3])
    return q


print(floats(), len(floats()), floats()[0] + 1.0)
print(strs(), strs()[1].upper(), len(strs()[0]))
print(nested(), len(nested()), len(nested()[0]), nested()[1][0])


# ── A tuple returned and then iterated by the caller ─────────────────────

def pair():
    q = (3, 4)
    return q


total = 0
for v in pair():
    total += v
print(total)

a, b = pair()
print(a, b, a + b)


# ── Module-level tuples ──────────────────────────────────────────────────

t = (10, 20)
words = ("alpha", "beta")


def get_t():
    return t


def alias_t():
    q = t
    return q


def sum_t():
    s = 0
    for v in t:
        s += v
    return s


def get_words():
    return words


print(get_t(), len(get_t()), get_t()[0])
print(alias_t(), len(alias_t()), alias_t()[1])
print(sum_t())
print(get_words(), get_words()[1], len(get_words()[0]))


# ── A one-element tuple and an empty one, which have their own shapes ────

def single():
    q = (7,)
    return q


def empty():
    q = ()
    return q


print(single(), len(single()), single()[0])
print(empty(), len(empty()))


# ── Lists must not have been disturbed by sharing the arm ────────────────

def loc_list():
    q = [1, 2, 3]
    return q


def loc_dict():
    q = {"a": 1}
    return q


print(loc_list(), len(loc_list()), loc_list()[1])
print(len(loc_dict()), loc_dict()["a"])
print("end")

# A local *set* belongs in this section too and is deliberately missing: it
# was already broken before the tuple arm existed, and still is.  `q = {1, 2,
# 3}; return q` puts `q` in `list_vars` — the set that cannot spell "set" —
# and the tag chain has no `return <Name in list_vars>` arm at all, so it
# reaches the i8_ptr branch's "ptr" default, which means *list*.  `len()` then
# measures a set object through a list's header and prints a pointer.
# `return {1, 2, 3}` written directly has its own arm and is correct, which is
# the same asymmetry that names the bug above.
# See BUG-RETURN-OF-LOCAL-SET-TAGGED-LIST.
