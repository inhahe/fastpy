# Regression: an owned (+1) temporary created *inside* a conditional
# expression arm lives in that arm's own basic block, but the enclosing
# statement's Model-2 refcount flush runs in the merge block — which the arm
# does not dominate.  The emitted `fpy_rc_decref` therefore referenced a value
# defined on only one path, and the LLVM verifier rejected the module with
#
#   Instruction does not dominate all uses!
#     %.895 = ptrtoint ptr %.894 to i64
#     call void @fpy_rc_decref(i32 2, i64 %.895)
#
# This affected `a if c else b` (both the FpyValue and the same-type paths) and
# the `and`/`or` short-circuit operands, i.e. every construct that produces a
# value from more than one predecessor block.  It went unnoticed because it
# only fires when an arm allocates — an f-string, a concat, a str() — so all
# the simple `x if c else y` tests over ints and literals stayed valid.
#
# The fix captures each arm's pending temps while the builder is still in that
# arm and re-registers them at the merge point as phis whose incoming value
# from every other predecessor is 0 (fpy_rc_decref no-ops on data == 0).  The
# +1 is untouched — only the *release site* moves — so this test has to check
# both that the value survives its use (no premature free) and that repeating
# it many times neither corrupts nor grows without bound (no double-free).


def pick(n):
    return "" if n < 0 else f"empty-{n}"


def pick_both(n):
    s = str(n)
    return f"yes-{s}" if s else f"no-{s}"


# Both arms taken, allocating arm included.
print(pick(7))
print(pick(-1))
print(pick_both(7))
print(pick_both(0))

# The result must still be alive after the merge — a premature release would
# make these reads garbage rather than the expected text.
r = pick_both(3)
print(r)
print(len(r))
print(r + "!")
print(r.upper())

# Repetition: a double-free shows up as a crash/corruption, a leak as unbounded
# growth.  The value is consumed each pass so the +1 must be released exactly
# once per iteration.
total = 0
i = 0
while i < 200:
    v = pick_both(i)
    total = total + len(v)
    i = i + 1
print(total)

# and/or short-circuit: every operand block is a predecessor of the merge.
def sc(a, b):
    x = a or f"[{a}|{b}]"
    y = a and f"({b}~{a})"
    return x + "/" + y


print(sc("A", "B"))
print(sc("", "B"))

# Three operands, so there are three predecessor blocks, not two.
def sc3(a, b, c):
    return a or f"<{b}>" or f"<{c}>"


print(sc3("a", "b", "c"))
print(sc3("", "b", "c"))

j = 0
acc = 0
while j < 100:
    acc = acc + len(sc(str(j % 2 - 1 + 1), "z"))
    j = j + 1
print(acc)

# Nested conditional expressions — the inner merge is itself an arm of the
# outer one, so the inner rejoin must already be complete when the outer
# capture runs.
def nested(n):
    return (f"a{n}" if n > 5 else f"b{n}") if n > 0 else f"c{n}"


print(nested(9))
print(nested(2))
print(nested(-1))

# A conditional arm used directly as a call argument, so the temp is consumed
# by a callee rather than stored.
print(len(f"p{1}" if 1 else "q"))
print(("x" if 0 else f"y{2}") + "-tail")

# Mixed-type arms take the FpyValue path (tag + data phis) rather than the
# same-type path — a different branch of the same emitter.
def mixed(flag):
    return f"str{flag}" if flag else 0


print(mixed(1))
print(mixed(0))

print("done")
