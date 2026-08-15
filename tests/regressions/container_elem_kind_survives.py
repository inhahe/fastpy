"""A container's *element* kind has to survive every hop its outer kind does.

Five bugs, one shape.  In each one the compiler worked out that some value was
a list (or a dict) and then dropped what the list held, and the reader of that
half-answer filled the missing element in with `VKind.INT` and read a pointer
as an integer.  `len()` on it answers 0; `==` compares addresses.

The thing worth remembering is that a *bare* tag was never the bug.  A bare
"list" declines to name the element, so the read is routed through the runtime
tag and comes out right.  It is the half-answer -- "list", written where
"list:str" was known -- that hurts, because every consumer treats "container
whose element I was not told" as "container of int".  So the fix in each case
is to name the inner kind, or (where the elements genuinely disagree) to say
`mixed` and mean it -- never to leave the slot empty and hope.

    A  BUG-METHOD-RETURN-ELEM-KIND-LOST
       `_func_ret_types` records what a body returns, element kind included,
       but every consumer looked it up by the callee's *bare* name, which a
       method call cannot use: two classes may each define `m`, and so may a
       module function.  So `c.m()[1]` had no element kind at all while the
       byte-identical `g()[1]` was right.  The CSA return-type pass now also
       runs over `Cls.meth` keys.

    B  BUG-DICT-VALUE-CONTAINER-ELEM-KIND-LOST-ON-BIND
       `d["k"][1]` was right and `e = d["k"]; e[1]` was not, because a dict's
       values were tracked as membership in the `_dict_var_*_values` *name
       sets* -- which can say "the values are lists" and nothing about what
       those lists hold -- and as a flat per-key tag "list".  A dict now
       carries a `value_type` `ValueType` alongside `elem_type` (they are
       different questions: `elem_type` is what *iterating* yields, which for
       a dict is a key).

    C  BUG-NESTED-LIST-ARG-INNER-ELEM-LOST
       `[["a", "bb"]]` passed as an argument tagged `list:list` -- outer named,
       inner lost.  Both the argument classifier and the return-type analysis
       needed generalising: only a *bare* parameter had an arm for
       `return rows[0]`, so `return rows[0][0]` matched nothing and fell to
       the pointer default in two independent places (the LLVM return type and
       the semantic return tag, which must agree).

    D  BUG-LIST-OF-DICTS-PARAM-VALUE-KIND-LOST
       `[{"a": "x"}]` tagged `list:dict`, so `ds[0]["a"]` knew it had a dict
       and not that its values were strs.

    E  control.  `take(mk_strs())` -- a call's return fed straight into a call
       -- is the shape that would break if the argument tag lost its suffix in
       transit.  It is here to stay honest, not because it ever failed.

Every line below is a value read *out* of a container whose element kind was
inferred, and every one of them is checked with `len()` rather than by
printing: printing a str is right even when the compiler thinks it is an int,
because print dispatches on the runtime tag.  `len()` does not.
"""

# ── A: a method's return type carries an element kind, like a function's ──


class C:
    def m(self):
        return ["b", [4, 5]]

    def s(self):
        return ["p", "qrs"]

    def via_self(self):
        return len(self.s()[1])


class Sub(C):
    pass


def g():
    return ["x", [10, 20, 30]]


c = C()
print(len(c.m()[1]))           # 2 -- a list element, not an int
print(len(c.s()[1]))           # 3 -- a str element
r = c.m()
print(len(r[1]))               # 2 -- and again through a binding
print(c.via_self())            # 3 -- `self.s()` resolves to the same record
print(len(Sub().s()[1]))       # 3 -- inherited: the MRO is walked
print(len(g()[1]))             # 3 -- the control that always worked


# ── B: a dict's value keeps its own element kind across a binding ──

d = {"k": ["a", [1, 2, 3]]}
print(len(d["k"][1]))          # 3 -- direct chain, correct before the fix
e = d["k"]
print(len(e[1]))               # 3 -- and through a binding, which was not

d2 = {"k": ["a", "bcd"]}
e2 = d2["k"]
print(e2[1], len(e2[1]))       # bcd 3

# Locals and globals are the same code path here; both were wrong.


def in_a_function():
    dd = {"k": ["a", "bcd"]}
    ee = dd["k"]
    return len(ee[1])


print(in_a_function())         # 3

# Two levels of nesting through a dict value.
d3 = {"k": [["a", "bb"], ["c"]]}
e3 = d3["k"]
print(len(e3[0]), len(e3[0][1]))   # 2 2

# A dict whose values disagree must not be pinned to the first one: the two
# keys below are read back through the runtime tag, and both are right.
mixed = {"n": 7, "s": "abcd"}
mn = mixed["n"]
ms = mixed["s"]
print(mn + 1, len(ms))         # 8 4


# ── C: a nested list argument keeps its inner element kind ──


def inner_first(rows):
    return rows[0][0]


def first_row(rows):
    return rows[0]


print(inner_first([["a", "bb"]]))            # a
print(len(inner_first([["a", "bb"]])))       # 1 -- a str, not a pointer
print(len(first_row([["a", "bb"]])))         # 2 -- one level up still works
print(len(inner_first([[[1, 2, 3], [4]]])))  # 3 -- inner elements are lists

# Three levels, to show the tag is peeled per index rather than special-cased
# at depth two.


def deep(rows):
    return rows[0][0][0]


print(len(deep([[["ab", "c"]]])))            # 2

# A slice is not an index: `xs[1:]` is the same kind as `xs`, so the peel
# must stop at it.


def tail_len(rows):
    return len(rows[1:])


print(tail_len([["a"], ["b"], ["c"]]))       # 2


# ── D: a list of dicts keeps its values' kind ──


def get_a(ds):
    return ds[0]["a"]


print(get_a([{"a": 1}, {"a": 2}]))           # 1
print(len(get_a([{"a": "x"}])))              # 1
print(len(get_a([{"a": [1, 2]}])))           # 2


# ── E: control -- a call's return used directly as a call argument ──


def mk_strs():
    return ["aa", "bbb"]


def take(xs):
    return len(xs[1])


print(take(mk_strs()))         # 3
xs = mk_strs()
print(take(xs))                # 3


def mk_ll():
    return [[1], [2, 3, 4]]


def take2(zs):
    return len(zs[1])


print(take2(mk_ll()))          # 3
ws = mk_ll()
print(take2(ws))               # 3
