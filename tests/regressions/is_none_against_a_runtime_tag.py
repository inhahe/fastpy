# BUG-IS-NONE-ON-TAGGED-VALUE
#
# `None` has no payload of its own — its data word is 0, exactly like the int
# 0 and like a null pointer — so the *only* thing that says a value is None is
# its runtime tag.  `_emit_expr_value` hands a container element back as the
# bare payload, so `is None` had nothing left to test and fell through to an
# AST fold that could only ask "did the compile-time inference say NONE?".
# For anything read out of a container the answer is no, and the comparison
# folded to a constant False:
#
#     m = [1, None]
#     if m[1] is None:        # never fired
#
# `== None` was wrong in strictly more cases than `is None`, because the
# value-based comparison path folds as soon as *either* side infers to NONE —
# so even `no == None` for a plain FV-backed variable answered False, though
# `no is None` had an arm and answered True.
#
# Both now reach the tag.  `== None` and `!= None` are routed through the
# identity emitter, since `None` is a singleton and equality against it *is*
# identity — and the operand is emitted exactly once either way, which is why
# the routing only happens when every operator in the comparison wants it.

m = [1, None, "s", 2.5]
d = {"a": None, "b": 1}

# --- the shape that never worked: an element of a container ---
print(m[1] is None, m[0] is None, m[2] is None, m[3] is None)
print(m[1] is not None, m[0] is not None)
print(d["a"] is None, d["b"] is None)

# --- `== None` has to agree with `is None`, for every shape ---
print(m[1] == None, m[0] == None, m[1] != None, m[0] != None)
print(d["a"] == None, d["b"] == None, d["a"] != None, d["b"] != None)

# --- through an FV-backed variable ---
v = m[1]
w = m[0]
print(v is None, w is None, v == None, w != None)
print(v is not None, w is not None)

# --- the guard actually branches ---
for i in range(4):
    if m[i] is None:
        print(i, "none")
    else:
        print(i, "value", m[i])

# --- the None literal on the left ---
print(None is m[1], None == m[1], None is m[0], None != m[0])

# --- statically-typed values are unaffected ---
x = 5
s = "hi"
n = None
print(x is None, s is None, n is None, n == None, x != None, n is not None)

# --- nested containers ---
nested = {"k": [None, 3]}
print(nested["k"][0] is None, nested["k"][1] is None)

# --- a tuple element ---
tp = (None, 7)
print(tp[0] is None, tp[1] is None, tp[0] == None)

# --- a call that returns None on one path only ---
def f(t):
    if t:
        return 1
    return None

print(f(1) is None, f(0) is None, f(0) == None, f(1) != None)

# --- the operand is emitted exactly once, whichever spelling is used ---
calls = 0


def val():
    global calls
    calls += 1
    return None


print(val() is None, calls)
print(val() == None, calls)
print(val() != None, calls)

# --- dict.get with a missing key ---
dd = {"x": 1}
r = dd.get("y")
r2 = dd.get("x")
print(r is None, r == None, r2 is None, r2 is not None)

# --- `is None` used as a filter ---
print([i for i in range(4) if m[i] is None])
print(sum(1 for i in range(4) if m[i] is not None))

# --- a chain that is not identity-like throughout still works ---
y = 3
print(1 < y < 5)

# (`p.a is None` for a polymorphic object field belongs here too, but the tag
# is lost at the *store* there, not at the test — BUG-ATTR-STORE-DROPS-TAG.
# Same for a module-level `None` read inside a function —
# BUG-GLOBAL-NONE-LOSES-TAG.)
