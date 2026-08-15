"""A list's element kind is what *all* its appends say, not the last one.

BUG-APPEND-ELEM-KIND-LAST-WRITE-WINS.

Three separate scans in the compiler answered "what does this list hold?" by
walking the `.append()` calls and writing each recognised kind straight into a
map.  Two things went wrong at once, and they compound:

  * each scan recognised its own subset of kinds, so anything it did not name
    simply did not update the map, and
  * the map was written unconditionally, so the *last* append that happened to
    be recognised decided the answer for the whole list.

`x.append(None); x.append("text")` is the smallest case.  There is no arm for
`None` in any of the three, so nothing disagreed with the `str` arm, the list
was recorded as holding strs, and the None came back as a NULL pointer:
`print` showed `(null)` instead of `None`.  Note that a list of *only* None was
fine, and `[None, "text"]` written as a literal was fine — it took an append of
an unrecognised kind followed by an append of a recognised one, which is why it
survived so long.

The rule now: appends that disagree on a known kind make the list `mixed` (a
complete answer, meaning "dispatch on the runtime tag"), and a single append
this scan cannot classify erases the element kind entirely (also correct — the
read then goes through the runtime tag).  Both are safe; what was not safe was
naming one of several kinds.

The cases below are all things that print or measure *differently* depending
on the recorded element kind, so a wrong tag shows up as a wrong answer rather
than a slower one.
"""

# ── the original: an unrecognised append before a recognised one ──


def mk():
    x = []
    x.append(None)
    x.append("text")
    return x


a, b = mk()
print(a, b)

r = mk()
print(r[0], r[1])
for v in mk():
    print(v)


# The same body as a method: the two live on separate code paths (the return
# type is recorded under `Cls.meth` rather than a bare name), and both were
# wrong here for the same reason.
class Box:
    def contents(self):
        x = []
        x.append(None)
        x.append("text")
        return x


n, t = Box().contents()
print(n, t)


# ── order must not matter ──


def mk_rev():
    x = []
    x.append("text")
    x.append(None)
    return x


print(mk_rev()[0], mk_rev()[1])


# ── two recognised kinds that disagree ──


def mixed_kinds():
    x = []
    x.append("s")
    x.append(2.5)
    return x


m = mixed_kinds()
print(m[0], m[1])
print(len(m[0]), m[1] + 0.5)


def str_and_list():
    x = []
    x.append("ab")
    x.append([1, 2, 3])
    return x


sl = str_and_list()
print(len(sl[0]), len(sl[1]))


# ── agreement still yields the precise kind ──
# The fix must not be "give up whenever there is more than one append".


def all_strs():
    x = []
    x.append("aa")
    x.append("bbb")
    return x


s = all_strs()
print(len(s[0]), len(s[1]), s[0] + s[1])


def all_floats():
    x = []
    x.append(1.5)
    x.append(2.5)
    return x


f = all_floats()
print(f[0] + f[1])


def all_lists():
    x = []
    x.append([1, 2])
    x.append([3])
    return x


ll = all_lists()
print(len(ll[0]), len(ll[1]), ll[0][1])


# ── the one-append case is unchanged ──


def one():
    x = []
    x.append("only")
    return x


print(len(one()[0]))
