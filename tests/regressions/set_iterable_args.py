"""Every set method that takes an "other" takes any iterable, not just a set.

BUG-SET-UPDATE-NON-SET-ITERABLE-SEGFAULTS.

`fastpy_set_update(FpyDict *a, FpyDict *b)` and its ten siblings were declared
to take a set and handed whatever the argument evaluated to.  Passing a list
gave that signature an `FpyList *`, whose `items`/`length`/`capacity` sit where
`keys`/`values`/`length` are read, so `b->keys[i]` returned an `FpyValue` built
out of a pointer and a capacity and the runtime dereferenced it: 0xC0000005,
no output, not even the `print` before the call.

That is the same shape as BUG-EMPTY-KWARGS-CALL-SEGFAULTS and
BUG-FOR-DICT-KEY-KIND-GUESSED -- one signature made to serve two container
kinds, and a live object of one type read as another.  The argument's kind is
usually not statically provable (it is a parameter here, in half these cases),
so the fix is a runtime tag switch, not a smarter compile-time guess: the
elements are materialised into a set by `fpy_iterable_as_set` and the eleven
algorithms are unchanged.

The point of testing all eleven rather than just `update` is that the
coercion is shared: if any one of them still takes the raw pointer it
segfaults here, and a segfault is not a wrong number, it is no output at all.
"""

# ── update() over every iterable kind ──


def upd(other):
    s = set()
    s.add(1)
    s.update(other)
    out = []
    for e in s:
        out.append(str(e))
    return sorted(out)


print(upd([2, 3]))          # list
print(upd((4, 5)))          # tuple
print(upd({6, 7}))          # set
print(upd([]))              # empty list adds nothing
print(upd("ab"))            # a str iterates as characters
print(upd({"k": 9}))        # a dict contributes its keys, not its values
print(upd(b"AB"))           # bytes iterate as ints (65, 66)


# ── The other two mutators, over a list ──


def diff_upd(other):
    s = {1, 2, 3}
    s.difference_update(other)
    return sorted(s)


def inter_upd(other):
    s = {1, 2, 3}
    s.intersection_update(other)
    return sorted(s)


def symdiff_upd(other):
    s = {1, 2, 3}
    s.symmetric_difference_update(other)
    return sorted(s)


print(diff_upd([1, 3]))
print(diff_upd((2,)))
print(inter_upd([2, 3, 9]))
print(inter_upd((1,)))
print(symdiff_upd([3, 4]))
print(symdiff_upd((1, 2, 3)))


# ── The four that build a new set ──


def uni(other):
    return sorted({1, 2}.union(other))


def inter(other):
    return sorted({1, 2, 3}.intersection(other))


def diff(other):
    return sorted({1, 2, 3}.difference(other))


def symdiff(other):
    return sorted({1, 2, 3}.symmetric_difference(other))


print(uni([3, 4]))
print(uni((2, 5)))
print(inter([2, 9]))
print(inter((1, 2)))
print(diff([1]))
print(diff((2, 3)))
print(symdiff([3, 4]))
print(symdiff((9,)))


# ── The three predicates ──


def subset(other):
    return {1, 2}.issubset(other)


def superset(other):
    return {1, 2, 3}.issuperset(other)


def disjoint(other):
    return {1, 2}.isdisjoint(other)


print(subset([1, 2, 3]))
print(subset((1,)))
print(superset([1, 2]))
print(superset((4,)))
print(disjoint([9]))
print(disjoint((2,)))


# ── The source set must not be mutated by the non-mutating ones ──
# A coercion that returned the argument's storage aliased into the result
# would show up here and nowhere else.

base = {1, 2, 3}
other_list = [3, 4]
_ = base.union(other_list)
_ = base.difference(other_list)
_ = base.intersection(other_list)
print(sorted(base))
print(sorted(other_list))


# ── An argument that is not iterable is a TypeError, not a crash ──
# The whole bug was that this path had no way to notice it was wrong.


def not_iterable(x):
    s = {1}
    try:
        s.update(x)
        return "no error"
    except TypeError:
        return "TypeError"


print(not_iterable(5))
print(not_iterable(2.5))
print(not_iterable(None))
print(not_iterable([5]))


# ── The constructor had the same bug, one call site over ──
# `set(x)` handed x's bare pointer to `fastpy_set_from_list`.  Note which
# cases used to work: str, tuple and list -- the three the compiler either
# special-cased or happened to guess right.  dict, bytes and set died, i.e.
# the bug appeared exactly where the compiler had *succeeded* in pinning the
# kind down, which is the opposite of where anyone would look for it.


def as_set(x):
    return sorted(set(x))


print(sorted(set("abc")))
print(sorted(set((1, 2, 2))))
print(sorted(set([3, 1])))
print(sorted(set({"k": 1})))
print(sorted(set(b"AB")))
print(sorted(set({7, 8})))
print(as_set("dd"))
print(as_set([9, 9, 8]))
print(sorted(set()))

# set(s) is a new set, not an alias for s.
src = {1, 2}
cp = set(src)
cp.add(3)
print(sorted(src), sorted(cp))


def bad_set(x):
    try:
        return sorted(set(x))
    except TypeError:
        return "TypeError"


print(bad_set(5))
print(bad_set(None))


# ── frozenset builds a set here ──
# The rest of the compiler already called a `frozenset(...)` call a SET --
# `isinstance(x, frozenset)` tests FPY_TAG_SET -- while the emitter sent it
# to the CPython bridge and returned a PyObject* wearing that tag.

fz = frozenset([2, 1, 2])
print(sorted(fz))
print(len(fz))
print(1 in fz, 5 in fz)
print(sorted(frozenset("ba")))
print(sorted(frozenset({3, 4})))
print(isinstance(fz, frozenset))
