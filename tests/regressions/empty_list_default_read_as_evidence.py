# Regression: `x = []` recorded the *fallback* element kind (int) into the
# variable's type tag, and the for-loop reader's F1 inline-GEP fast path then
# read that fallback back as though it were evidence.
#
# `_infer_list_elem_type([])` has to answer with some kind, and answers INT.
# Writing that answer into the tag turned "I had to say something" into "I
# know it holds ints".  `_is_confident_elem_type` asks only whether an
# element kind is *present*, so it reported the list confidently INT, and
# `for v in x:` was then allowed to skip `fastpy_list_get_fv`, GEP straight
# to the data half, and hardcode the tag to 0 (INT) — while the appends had
# stored tag 2 (STR).  `v == '|'` therefore compared an int against a string
# and answered False forever.
#
# It only bit when the append pre-scan could *not* classify the appended
# expression, because a classifiable append overrides the empty-list default
# with real evidence.  A for-loop variable over a list of strs is exactly
# such an unclassifiable expression, which is why the flat-append idiom
# below — the one a shell's tokeniser uses — miscompiled while the same
# program with a literal `x.append("a")` was correct.
#
# The same fast path also skipped the element's `fpy_rc_incref` while the
# loop variable was still decref'd on the next iteration, so a wrongly-
# confident list of pointers was a refcount underflow as well as a
# mistyped read.

print("--- 1. append of an unclassifiable expression (the shell tokeniser) ---")


def count_bars():
    toks = ["a", "b"]
    toks2 = []
    for t in toks:
        toks2.append(t)
    toks2.append("|")
    n = 0
    for t in toks2:
        if t == "|":
            n = n + 1
    return n


print(count_bars())

print("--- 2. the elements survive as strings, not as addresses ---")


def echo_back():
    src = ["alpha", "beta"]
    dst = []
    for s in src:
        dst.append(s)
    out = []
    for s in dst:
        out.append(len(s))
    return out


print(echo_back())

print("--- 3. floats too: an unclassifiable append must not read as int ---")


def sum_floats():
    src = [1.5, 2.25]
    dst = []
    for v in src:
        dst.append(v)
    total = 0.0
    for v in dst:
        total = total + v
    return total


print(sum_floats())

print("--- 4. a classifiable append keeps its evidence (and its fast path) ---")


def literal_appends():
    xs = []
    xs.append(1)
    xs.append(2)
    xs.append(3)
    total = 0
    for v in xs:
        total = total + v
    return total


print(literal_appends())


def literal_float_appends():
    xs = []
    xs.append(1.5)
    xs.append(2.5)
    total = 0.0
    for v in xs:
        total = total + v
    return total


print(literal_float_appends())

print("--- 5. mixed appends still dispatch on the runtime tag ---")


def mixed():
    xs = []
    xs.append(1)
    xs.append("two")
    xs.append(3.5)
    xs.append(None)
    out = []
    for v in xs:
        out.append(str(v))
    return out


print(mixed())

print("--- 6. an empty list that stays empty iterates zero times ---")


def never_appended():
    xs = []
    n = 0
    for v in xs:
        n = n + 1
    return n


print(never_appended())

print("--- 7. indexing the same list, not just iterating it ---")


def by_index():
    src = ["one", "two", "three"]
    dst = []
    for s in src:
        dst.append(s)
    return dst[0] + "/" + dst[2]


print(by_index())
