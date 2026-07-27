# BUG-BOOL-PLUS-INT-YIELDS-FLOAT
#
# The inlined fast paths in `_emit_binop_unknown` split on "both runtime tags
# == INT" and sent everything else down the *float* edge.  CPython's `bool` is
# a subclass of `int`, so a BOOL-tagged operand belongs on the integer edge —
# but it failed the `== INT` test, and the consequences went well past the
# spurious `.0` the bug was filed for:
#
#   True + 3   gave 4.0   (right value, wrong type)
#   True % 2   gave 5e-324 (the integer result 1, bitcast to a double)
#   True << 2  raised "unsupported operand type(s) for <<: 'float' and 'float'"
#
# Two smaller things fell out of the same rule.  `&`, `|` and `^` of two bools
# are a *bool* in CPython — `True & False` is `False`, not `0` — while the
# shifts and any mixed bool/int pair widen to int.  And `+True` is `1`: unary
# plus is the identity on the value but not on the type, so it may not simply
# hand the BOOL tag back.
#
# Every value below is read out of a heterogeneous list, which is what makes it
# runtime-tagged rather than a compile-time constant.

m = [3, 4.5, True, False, 2 ** 80, "ab"]
n, fl, t, f, big, s = m[0], m[1], m[2], m[3], m[4], m[5]

# --- arithmetic: a bool is an int, and stays one ---
print(t + n, n + t, t - n, n - t, t * n, t // n, t % n)
print(t + t, t * t, t - t, f + f, f * n, f - t)

# --- true division is the one that really is a float ---
print(t / n, t / 2, f / 2)

# --- against a float, the float edge is correct ---
print(t + fl, fl + t, t * fl, f + fl)

# --- against a BigInt, the runtime edge is correct ---
print(t + big, big + t, t * big, f + big)

# --- bitwise: bool op bool stays bool, everything else widens ---
print(t & f, t | f, t ^ f)
print(t & t, t | t, t ^ t, f & f, f | f, f ^ f)
print(t & n, n & t, t | n, t ^ n)
print(t << 3, t >> 1, f << 3)

# --- unary: `+True` is 1, `-True` is -1 ---
print(+t, +f, -t, -f, +n, +fl, -fl)

# --- results are ordinary ints downstream ---
print(t + t + t, (t + t) * 2, (t + n) // 2)
print([t + n for _ in range(3)])
print(list(range(t + n)))
print("x" * (t + t), s * t)

# --- a bool that reaches the runtime edge via a loop variable ---
for x in [True, False, 5, 2.5]:
    print(x + t, x * t, x - f)
