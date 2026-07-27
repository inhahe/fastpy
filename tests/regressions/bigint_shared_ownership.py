"""Every incref arm must have a decref arm, and vice versa.

BUG-BIGINT-INCREF-MISSING.

`fpy_rc_decref` (runtime/objects.c) has a `case FPY_TAG_BIGINT` that
decrements the BigInt's refcount and frees it at zero.  `fpy_rc_incref`,
right above it, did *not* — BIGINT fell into the `default: break` arm
alongside INT/FLOAT/BOOL/NONE, the genuinely unboxed tags.  So every
incref of a BigInt was a silent no-op while every decref really counted
down.  A BigInt with a single owner survived; a BigInt with *two* owners
was freed by the first release, and the second one read freed memory.

The narrowest shape is two loops sharing a loop variable:

    for x in [2 ** 80]:   # x borrows the element, "increfs" it — no-op
        print(int(x))
    #                     # the temp list is released here, freeing the BigInt
    for x in [1]:         # rebinding x decrefs the old value → use-after-free
        print(int(x))

which is why it needed *two* loops to show up: with one loop nothing ever
touches the variable after the list dies.  Natively this was a ~15%
`STATUS_HEAP_CORRUPTION` (0xC0000374) abort — intermittent because
whether the freed block had been reused yet is allocator-state dependent.
It had been mis-filed twice as a regression-suite flake before the exit
code was actually captured; under ASan it is deterministic.

Every section below creates a BigInt with more than one owner and then
drops the owners in an order that lets the runtime notice.  Correct
output is necessary but not sufficient — the real assertion is that the
process exits 0 (and that ASan is silent under tools/pure_harness.py).
"""


# ── The minimal repro: a loop variable outliving its list ────────────────

for x in [2 ** 80]:
    print(int(x))
for x in [1]:
    print(int(x))

# …and with the second loop's list also holding heap numbers.
for y in [2 ** 90, 2 ** 91]:
    print(y)
for y in [2 ** 92]:
    print(y)
for y in ["done"]:
    print(y)


# ── A name and a container holding the same BigInt ───────────────────────

b = 2 ** 80
holder = [b, b, b]
print(holder[0] == b, len(holder))
holder = []          # drops three references at once
print(b, b * 2)      # b must still be alive and correct

d = {"a": b, "b": b}
print(d["a"] == b, d["b"] == b)
d = {}
print(b + 1 - 1 == b)


# ── Two containers sharing one element ───────────────────────────────────

shared = 2 ** 100
one = [shared]
two = [shared, shared]
print(one[0] == shared, two[0] == two[1])
one = []
print(two[0] == shared)
two = []
print(shared // (2 ** 50))


# ── Nested containers: the inner list owns, the outer owns the inner ─────

inner = [2 ** 85]
outer = [inner, inner]
print(outer[0][0], inner[0])
inner = []
print(len(outer), len(outer[1]))
outer = []


# ── Across a call boundary ───────────────────────────────────────────────

def echo(v):
    return v


def pick(vs):
    out = vs[0]
    return out


# A returned *list element* is printed rather than compared: a BigInt that
# reaches a comparison without a statically BIGINT-typed operand is compared
# by pointer, which is BUG-BIGINT-COMPARES-BY-POINTER — a separate bug, and
# not what this test is asserting.
big = 2 ** 120
print(echo(big) == big)
print(pick([big, big]))
print(pick([2 ** 121]))

# The returned element outliving the list it came from.
def first_big():
    tmp = [2 ** 130, 2 ** 131]
    return tmp[0]


kept = first_big()
print(kept)
print(kept * 2)


# ── Repeated rebinding of one name across kinds ──────────────────────────

z = 2 ** 80
z = 2 ** 81
z = 1
z = 2 ** 82
z = "s"
z = 2 ** 83
print(z == 2 ** 83)

# The same, driven by a loop so the rebind runs many times.
acc = 0
for i in range(50):
    t = 2 ** 80 + i
    acc = acc + (t - 2 ** 80)
print(acc)

for j in range(20):
    for k in [2 ** 80, 1, 2 ** 81]:
        pass
print(k == 2 ** 81)


# ── Tuples and sets take the same release path ───────────────────────────

tup = (2 ** 95, 2 ** 95)
print(tup[0] == tup[1])
tv = tup[0]
tup = ()
print(tv == 2 ** 95)

# `2 ** 96 in st` is left out: a BigInt key hashes by its *address*
# (BUG-HASH-BY-POINTER-FOR-HEAP-VALUES), which is again a separate bug.
st = {2 ** 96}
print(len(st))
st = set()
print(2 ** 96 == 2 ** 96)


# ── The scalar tags must be unaffected ───────────────────────────────────

for x in [1, 2]:
    print(x)
for x in [1.5]:
    print(x)
for x in ["a", "b"]:
    print(x)
for x in [None]:
    print(x)
print("end")
