# BUG-ALIASED-LOCAL-RETURN-KIND-LOST
#
# A function's return type is inferred by scanning the body for the *shape* of
# the expression each local is assigned.  A bare Name has no shape, so one
# extra copy before the `return` dropped everything that had been worked out:
#
#     def f():
#         raw = "abcdef"
#         out = raw
#         return out       # inferred int; len() answered 0
#
# The scan now propagates kinds along plain name-to-name assignments, as a
# fixpoint — `ast.walk` does not visit in source order, and an alias chain can
# be any length.
#
# Found while fixing BUG-FILEREAD-FN-RETTAG, which needed the same propagation
# to carry a file read through one more local.
#
# The same scan had a second, narrower fault.  The arm for the string-building
# pattern `result = result + ch` tested "is the left operand a known str" from
# *inside* the arm rather than in its guard, so it claimed every other `+` as
# well and did nothing with it — shadowing the general "is this expression
# statically a str" test that came after.  `raw = str(n) + "x"` is
# unambiguously a str and was typed int for exactly that reason.


# --- the original shape ---
def aliased_const():
    raw = "abcdef"
    out = raw
    return out


print("const:", len(aliased_const()), aliased_const().upper())


# --- a chain, so one pass is not enough ---
def aliased_chain():
    a = "hello"
    b = a
    c = b
    d = c
    return d


print("chain:", len(aliased_chain()), aliased_chain().capitalize())


# --- the alias assigned before the value it aliases, in source order ---
# (Only reachable because the scan is flow-insensitive; the point is that the
# fixpoint does not depend on which order the assignments are visited in.)
def aliased_out_of_order(flag):
    if flag:
        out = src
        return out
    src = "zzzz"
    out = src
    return out


print("order:", len(aliased_out_of_order(0)))


# --- the shadowed arm: a `+` that is a str without either side being a str var ---
def concat_call(n):
    raw = str(n) + "x"
    out = raw
    return out


print("call+lit:", concat_call(12), len(concat_call(12)))


# --- the arm's original job still works: result = result + ch ---
def build(n):
    result = ""
    i = 0
    while i < n:
        ch = "ab"
        result = result + ch
        i += 1
    return result


print("build:", build(3), len(build(3)))


# --- and the mirrored ch + result ---
def build_left(n):
    result = ""
    i = 0
    while i < n:
        result = "z" + result
        i += 1
    return result


print("build left:", build_left(4), len(build_left(4)))


# --- an f-string through an alias ---
def aliased_fstring(v):
    s = f"[{v}]"
    t = s
    return t


print("fstring:", aliased_fstring(9), len(aliased_fstring(9)))


# --- a list through an alias ---
def aliased_list():
    xs = [1, 2, 3]
    ys = xs
    return ys


_l = aliased_list()
print("list:", len(_l), _l[2])


# --- a dict through an alias ---
def aliased_dict():
    d = {"a": 1, "b": 2}
    e = d
    return e


_d = aliased_dict()
print("dict:", len(_d), _d["b"])


# --- an object through an alias ---
class Box:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


def aliased_obj(v):
    b = Box(v)
    c = b
    return c


print("obj:", aliased_obj(41).get())


# --- a float through an alias ---
def aliased_float():
    x = 1.5
    y = x
    return y * 2.0


print("float:", aliased_float())


# --- the alias is reassigned to something of the same kind afterwards ---
def realiased():
    a = "one"
    b = a
    c = "three"
    b = c
    return b


print("realiased:", realiased(), len(realiased()))


# --- a str method result through two aliases ---
def method_aliased(s):
    a = s.upper()
    b = a
    c = b
    return c


print("method:", method_aliased("mixed"), len(method_aliased("mixed")))


# --- aliases in a nested function must not leak into the outer one ---
def outer(n):
    def inner():
        s = "inner"
        t = s
        return t

    total = len(inner())
    return total + n


print("nested:", outer(1))


# --- called enough times that a stale or shared inference would show ---
def many(n):
    total = 0
    for i in range(n):
        s = "x" * (i % 3 + 1)
        t = s
        total += len(t)
    return total


print("many:", many(300))
