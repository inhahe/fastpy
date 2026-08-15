"""Two callers describing one list parameter with different precision agree.

BUG-PARAM-TAG-PROPAGATION-MERGES-COARSELY.

A parameter's tag is merged across call sites.  Two copies of that merge
rule existed: the direct call-site loop, which knew that a bare `"list"`
and a `"list:int"` are the same type said with different precision, and
the interprocedural propagation in `_csa_propagate_ret_types`, which knew
only bool-vs-int and called everything else a conflict.

The copies agreed for as long as the call-site scan never produced an
element kind — every list argument was a bare `"list"`, so the two tags
being merged were equal and the coarse copy never had to decide.  The
moment the classifier learned to say `"list:int"`, the copy left behind
started reporting a conflict, and a conflict for a *parameter* is spelled
`"mixed"`, which means "an FpyValue of unknown kind" — not "a list whose
elements vary".  The callee then stopped treating the parameter as a list
at all:

    def mean(data):
        total = 0.0
        for x in data:
            total += x
        return total / len(data)

    def variance(data):
        m = mean(data)               # <- propagates variance's tag to mean
        ...

    print(mean([1, 2, 3, 4, 5]))     # list:int
    print(mean(list(range(1, 11))))  # list

`mean` merged to `"mixed"` and the program segfaulted in `len(data)`,
which read a type tag as a pointer.

The shape that matters is: a function called both with a list *literal*
(precisely tagged) and with a list-producing *call* (tagged only "list"),
and reached a second time through another function's parameter, which is
what routes the merge through the propagation copy rather than the direct
one.  Every section below is that shape with a different element kind.
"""


# ── The original report: float accumulation over an int list ─────────────

def mean(data):
    if len(data) == 0:
        return 0.0
    total = 0.0
    for x in data:
        total += x
    return total / len(data)


def variance(data):
    if len(data) < 2:
        return 0.0
    m = mean(data)
    total = 0.0
    for x in data:
        diff = x - m
        total += diff * diff
    return total / (len(data) - 1)


print(mean([1, 2, 3, 4, 5]))
print(mean(list(range(1, 11))))
print(round(variance([2, 4, 4, 4, 5, 5, 7, 9]), 4))
print(round(variance(list(range(1, 11))), 4))


# ── The plainly-visible symptom: a slice of a downgraded parameter ───────
# `"mixed"` is not a list, so the callee's slice produced nothing and its
# length answered 0.  Both spellings are here because the bug reaches the
# parameter only through the second hop, where the propagation copy of the
# merge runs.

def rest(xs):
    return xs[1:]


def rest_len_via(xs):
    return len(rest(xs))


print(len(rest([1, 2, 3])), rest_len_via([1, 2, 3]))
print(rest_len_via(list(range(5))), len(rest(list(range(5)))))


# ── len() alone is enough to show it: it read a tag as a pointer ─────────

def size(xs):
    return len(xs)


def size_twice(xs):
    return size(xs) + size(xs)


print(size([1, 2, 3]), size(list(range(7))))
print(size_twice([1, 2, 3]), size_twice(list(range(7))))


# ── str elements, where the merged tag is list:str vs list ───────────────

def joined(ws):
    out = ""
    for w in ws:
        out = out + w
    return out


def joined_upper(ws):
    return joined(ws).upper()


print(joined(["a", "b", "c"]))
print(joined(list("xyz")))
print(joined_upper(["a", "b"]), joined_upper(list("pq")))


# ── float elements ───────────────────────────────────────────────────────

def total_of(fs):
    t = 0.0
    for f in fs:
        t += f
    return t


def doubled_total(fs):
    return total_of(fs) * 2


print(total_of([1.5, 2.5]), doubled_total([1.5, 2.5]))
print(total_of([0.25, 0.75, 1.0]))


# ── A genuine disagreement must still be reported as one ─────────────────
# `list:int` meeting `list:str` is not two precisions of one type, and the
# merge says "mixed", which routes the read through the runtime tag.

def first_of(vs):
    return vs[0]


def first_via(vs):
    return first_of(vs)


print(first_of([1, 2]), first_of(["a", "b"]))
print(first_via([1, 2]), first_via(["a", "b"]))


# ── Numeric widening still holds across the same merge ───────────────────

def plus_one(n):
    return n + 1


def plus_one_via(n):
    return plus_one(n)


print(plus_one(1), plus_one(True))
print(plus_one_via(1), plus_one_via(True))
print("end")
