"""An attribute holding a container remembers what kind it is.

BUG-CTOR-PARAM-CONTAINER-ATTR-ELEM-KIND-LOST, and the tuple half of the
same wound.

`_class_container_attrs` recorded, per class, two *sets of attribute
names*: `list_attrs` and `dict_attrs`.  Two name-sets can answer only
"is this attribute list-ish?" and "is it dict-ish?".  They cannot spell
"tuple", and they cannot carry an element kind.  So both of these were
wrong, each in its own way:

    class A:
        def __init__(self):
            self.t = ("a", [1, 2, 3])

    a = A()
    for v in a.t[1]:          # segfault: a.t was in neither bucket, so
        print(v)              # a.t[1] fell through to the loaded i64 —
                              # INT — and `for` chose the native list
                              # loop over an FpyValue.

    class B:
        def __init__(self, items):
            self.items = items

    b = B(["a", [1, 2, 3]])
    print(len(b.items[1]))    # 0: `items` reached the list bucket, but a
                              # bucket carries no element kind, so the
                              # element defaulted to INT.

The fix replaces the two sets with `_class_attr_vtypes`: class -> attr ->
`ValueType`, which holds a kind *and* an element kind.  The sets survive
as the coarse yes/no views their older call sites still ask for.  The
recurring mistake this file guards against is a set of names standing in
for a map to a type.

Widening `list_attrs` to include tuples — the one-token version of this
fix — is what the `list()` cases below rule out: `list()` asks
`_is_list_expr`, and a tuple attribute answering "yes" makes `list(p.pos)`
hand the tuple straight back instead of converting it.
"""


# ── A tuple attribute from a literal ─────────────────────────────────────

class A:
    def __init__(self):
        self.t = ("a", [1, 2, 3])


a = A()
print(a.t[0], len(a.t[1]))
for v in a.t[1]:
    print(v)


# ── The same attribute, arriving through a constructor parameter ─────────
# The element kind here exists only at the call site.

class B:
    def __init__(self, items):
        self.items = items


b = B(("a", [1, 2, 3]))
print(b.items[0], len(b.items[1]))
for v in b.items[1]:
    print(v)


class C:
    def __init__(self, items):
        self.items = items


c = C(["a", [4, 5]])
print(c.items[0], len(c.items[1]))
for v in c.items[1]:
    print(v)


# Two call sites of the same kind must agree rather than cancel out.

class D:
    def __init__(self, items):
        self.items = items


d1 = D(["a", [1, 2, 3]])
d2 = D(["b", [4, 5]])
print(len(d1.items[1]), len(d2.items[1]))


# ── `list()` on a tuple attribute is still a conversion ──────────────────
# The whole reason the fix records a type rather than widening the list
# bucket: `_is_list_expr` must keep answering "no" here.

class P:
    def __init__(self):
        self.pos = (1.5, 2.5)


p = P()
print(list(p.pos))
print(len(p.pos), p.pos[0] + p.pos[1])


class Q:
    def __init__(self, pos):
        self.pos = pos


q = Q((3.5, 4.5))
print(list(q.pos), q.pos[1] + 1.0)


# ── Element kinds other than "mixed" ─────────────────────────────────────

class Holder:
    def __init__(self):
        self.strs = ("ab", "cde")
        self.floats = (1.5, 2.5)
        self.lists = ([1, 2], [3, 4, 5])
        self.dicts = ({"a": 1}, {"b": 2, "c": 3})
        self.lstrs = ["ab", "cde"]


h = Holder()
print(len(h.strs[1]), h.strs[0])
print(h.floats[1] + 1.0)
print(len(h.lists[1]), len(h.lstrs[1]))
print(len(h.dicts[1]), h.dicts[1]["c"])

for s in h.strs:
    print(len(s))
for lst in h.lists:
    print(len(lst))


# ── Two classes may use the same attribute name ──────────────────────────
# The lookup is per class; when the class of an expression is unknown and
# two classes disagree it must decline rather than pick one.

class E:
    def __init__(self):
        self.t = ("x", [7, 8])


class F:
    def __init__(self):
        self.t = [9, 10, 11]


e = E()
f = F()
print(e.t[0], len(e.t[1]), len(f.t))


# ── Inheritance: the child's own assignment wins ─────────────────────────

class Base:
    def __init__(self):
        self.data = ("base", [1])


class Child(Base):
    def __init__(self):
        self.data = ("child", [1, 2, 3])


print(len(Base().data[1]), len(Child().data[1]))


class Inheritor(Base):
    def total(self):
        n = 0
        for _ in self.data[1]:
            n += 1
        return n


print(Inheritor().total())

print("end")
