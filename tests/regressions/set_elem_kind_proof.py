"""A set's element kind may be proven, and every unproven shape must stay dynamic.

PERF-INT-KEYED-DICT-UNPROVABLE-IN-A-WHILE-LOOP, the speed half of
BUG-FOR-DICT-KEY-KIND-GUESSED.

`_emit_for_dict` used to call every set an int set ("most common").  That was a
guess, and a wrong static kind is a wrong program: the loop variable's FpyValue
is rebuilt by the next statement from the *static* tag, discarding the runtime
one, so a str element tagged int comes back out as an address.  Removing the
guess was correct and cost 1.69x on `set iterate 100K x 20`, because for an
int set the guess had happened to be right.

Speed that came from a guess has to be re-earned by proof, so `_set_elem_tag`
now proves it: a set is int-element'd when every `.add()` reachable in its
scope adds a provably-int value.  `_expr_is_provably_int` proves int literals,
`len`/`int`/`abs`/`ord`/`hash` calls, integer arithmetic over provably-int
operands, and names whose every binding is itself provably int -- including the
self-referential `i = i + 1`, which is why a counter in a `while` loop works.

The interesting half of this file is everything the prover must *refuse*.  A
False costs a slow loop; a wrong True costs a segfault, so:

  * `s = set()` is not evidence of anything and must not be read as such.
  * `.update()` / `|=` bring in elements from a container whose kind is not
    being proven, so they poison the answer rather than being skipped.
  * A parameter's kind comes from call sites, not from walking the body.
  * A name bound *only* in terms of itself is not proven, however int-looking.
  * `/` is true division and yields a float, so it is not an int operator.
  * `True` is not an int here, though `isinstance(True, int)` says otherwise.
  * A binding this cannot read -- tuple unpack, `global`, `del`, `for` over an
    unknown iterable -- has to make the whole name unreadable, because a
    binding that goes unread is exactly how a name acquires a kind it hasn't
    got.

And the lookups are scoped by (function, variable): two functions may each
have a local `s` or `i` and they are not the same variable.  Answering from
the wrong one is BUG-UNCALLED-FN-PARAM-NAME-POISONS-A-CALLED-ONE again.
"""

# ── The shape the proof exists for: a counter in a while loop ──


def int_set_while(n):
    s = set()
    i = 0
    while i < n:
        s.add(i)
        i = i + 1
    total = 0
    for e in s:
        total = total + e
    return total


print(int_set_while(0))
print(int_set_while(1))
print(int_set_while(10))


# ── Every provable spelling of an int element ──


def by_augassign(n):
    s = set()
    i = 0
    while i < n:
        s.add(i)
        i += 1
    return sum(sorted(s))


def by_arithmetic(n):
    s = set()
    i = 0
    while i < n:
        s.add(i * 2 + 1)
        i = i + 1
    return sum(sorted(s))


def by_len(words):
    s = set()
    for w in words:
        s.add(len(w))
    return sorted(s)


def by_range():
    s = set()
    for i in range(5):
        s.add(i)
    return sorted(s)


def by_literals():
    s = set()
    s.add(3)
    s.add(1)
    s.add(3)
    return sorted(s)


print(by_augassign(5))
print(by_arithmetic(5))
print(by_len(["a", "bb", "ccc", "dd"]))
print(by_range())
print(by_literals())


# ── Must NOT be proven int: the element really is a string ──
# Under the old guess these printed addresses or died.


def str_set_adds():
    s = set()
    s.add("a")
    s.add("bb")
    out = []
    for e in s:
        out.append(e)
    return sorted(out)


def str_set_from_loop(words):
    s = set()
    for w in words:
        s.add(w)
    out = []
    for e in s:
        out.append(e + "!")
    return sorted(out)


print(str_set_adds())
print(str_set_from_loop(["q", "r"]))


# ── A float counter is not an int counter (`/` is true division) ──


def float_set():
    s = set()
    i = 0
    while i < 4:
        s.add(i / 2)
        i = i + 1
    out = []
    for e in s:
        out.append(e)
    return sorted(out)


print(float_set())


# ── `True` is not an int, though isinstance() says it is ──


def bool_set():
    s = set()
    s.add(True)
    s.add(False)
    out = []
    for e in s:
        out.append(str(e))
    return sorted(out)


print(bool_set())


# ── A set filled from a parameter: no call-site walk, so no claim ──


def add_one(v):
    s = set()
    s.add(v)
    return s


def show(s):
    out = []
    for e in s:
        out.append(str(e))
    return sorted(out)


print(show(add_one(7)))
print(show(add_one("seven")))


# ── `update` and `|=` bring in elements of an unproven kind ──
# What matters here is that a set touched by `update` at all stops being
# provably int, so `via_update` must print its str element rather than that
# element's address.  The list and str arguments are the ones that used to
# segfault before BUG-SET-UPDATE-NON-SET-ITERABLE-SEGFAULTS was fixed; they
# are also the cases where "the elements came from somewhere the prover never
# looked" is most obviously true.


def via_update(other):
    s = set()
    s.add(1)
    s.update(other)
    out = []
    for e in s:
        out.append(str(e))
    return sorted(out)


print(via_update({"x", "y"}))
print(via_update({2, 3}))
print(via_update(["x", "y"]))
print(via_update([2, 3]))
print(via_update("xy"))


# ── Same variable names in different functions are different variables ──
# `i` is an int here and a str next door; neither may answer for the other.


def scoped_int():
    s = set()
    i = 0
    while i < 3:
        s.add(i)
        i = i + 1
    total = 0
    for e in s:
        total = total + e
    return total


def scoped_str():
    s = set()
    i = "k"
    s.add(i)
    out = []
    for e in s:
        out.append(e)
    return sorted(out)


print(scoped_int())
print(scoped_str())


# ── A dead function must not answer for a live one ──


def unused_counter(i):        # never called
    return i


def live_counter():
    s = set()
    i = 0
    while i < 4:
        s.add(i)
        i = i + 1
    total = 0
    for e in s:
        total = total + e
    return total


print(live_counter())


# ── A counter the prover cannot read makes the set unproven ──
# Tuple unpacking binds `i` in a form the collector deliberately refuses.


def unpacked_counter():
    s = set()
    i, j = 0, 1
    while i < 3:
        s.add(i)
        i = i + 1
    total = 0
    for e in s:
        total = total + e
    return total


print(unpacked_counter())


# ── Mixed element kinds: nothing may be claimed ──

mixed = set()
mixed.add(1)
mixed.add("a")
mixed.add(2.5)
kinds = []
for e in mixed:
    kinds.append(str(e))
print(sorted(kinds))


# ── Set literals on both sides still work ──

si = {1, 2, 3}
t = 0
for e in si:
    t = t + e
print(t)

ss = {"p", "q"}
acc = []
for e in ss:
    acc.append(e)
print(sorted(acc))


# ── The proven loop variable used every way a wrong tag would show up ──


def uses_proven(n):
    s = set()
    i = 0
    while i < n:
        s.add(i)
        i = i + 1
    last = None
    count = 0
    parts = []
    for e in s:
        last = e                 # the rebinding that crashed
        count = count + 1
        parts.append(str(e))
        if e in s:
            pass
    return last, count, sorted(parts)


print(uses_proven(3))
print(uses_proven(1))
