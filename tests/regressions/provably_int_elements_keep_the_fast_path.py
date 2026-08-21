# Regression: an element expression that can only be an int must say so.
#
# `ELEM_KIND_UNKNOWN` (see unevidenced_list_elem_kind_is_not_int.py) made "I
# could not tell" distinguishable from "the elements are ints", which is what
# stopped the readers guessing.  But honesty is only half the job: every case
# that *can* be proven has to keep answering positively, or the fix costs a
# runtime tag check per element on lists whose elements cannot be anything but
# ints.
#
# `[i * i for i in range(n)]` is the commonest list comprehension in Python.
# Before the sentinel it reached the reader as INT by accident — the arm fell
# through to the old int default, which happened to be right.  Afterwards it
# reached the reader as "unknown" and declined the inline path.  It now
# answers INT on purpose, via `_provably_int`.
#
# The point of this file is that the *proof* is sound, not that it is fast:
# every case below is checked for the right value, and the shapes that are
# deliberately NOT provable (true division, bool, a name from outside a
# `range`) are checked to still produce correct results now that they take
# the declining path.

# --- 1. The shape that motivated the change -----------------------------
data = [i * i for i in range(10)]
print(len(data))                      # 10
print(data[0], data[3], data[9])      # 0 9 81
print(sum(data))                      # 285

result = [x for x in data if x % 3 == 0]
print(len(result))                    # 4  (0, 9, 36, 81)
print(result[0], result[3])           # 0 81

# --- 2. Every int-in/int-out operator ------------------------------------
n = 4
print([i + 1 for i in range(n)])
print([i - 1 for i in range(n)])
print([i * 3 for i in range(n)])
print([i // 2 for i in range(n)])
print([i % 3 for i in range(n)])
print([i << 2 for i in range(n)])
print([i >> 1 for i in range(n)])
print([i | 8 for i in range(n)])
print([i ^ 5 for i in range(n)])
print([i & 6 for i in range(n)])
print([-i for i in range(n)])
print([~i for i in range(n)])
print([i ** 2 for i in range(n)])

# Nested arithmetic over two range targets.
print([i * 10 + j for i in range(3) for j in range(2)])

# --- 3. `len` is an int, and the elements really are ints ----------------
words = ["a", "bb", "ccc"]
lens = [len(w) for w in words]
print(lens[0] + lens[1] + lens[2])    # 6
print(sum(lens))                      # 6

# --- 4. Arithmetic in a list *literal* -----------------------------------
lit = [1 + 2, 3 * 4, 10 // 3]
print(lit[0], lit[1], lit[2])         # 3 12 3
print(sum(lit))                       # 18

# --- 5. The shapes that must NOT be claimed as int -----------------------
# True division yields a float even for two ints.  If `_provably_int` ever
# claimed `/`, these would be read as the doubles' bit patterns.
halves = [i / 2 for i in range(5)]
print(halves[0], halves[1], halves[4])   # 0.0 0.5 2.0
total = 0.0
for h in halves:
    total = total + h
print(total)                             # 5.0

# `not x` is a bool, which has its own kind and its own tag.
flags = [not (i % 2) for i in range(4)]
print(flags[0], flags[1])                # True False

# A name bound outside any `range` target is not provably anything.  This is
# the case the whole sentinel exists for: it must decline and read the tag.
src = ["one", "two", "three"]
copied = [s for s in src]
print(copied[0] + "/" + copied[2])       # one/three

mixed_src = [1.5, 2.25]
copied_f = [v for v in mixed_src]
tot = 0.0
for v in copied_f:
    tot = tot + v
print(tot)                               # 3.75

# `i * s` where s is a str is a str, not an int — the operand is a Name that
# is not a range target, so the BinOp is not provable and must decline.
sep = "-"
bars = [sep * i for i in range(4)]
print(bars[0] + "|" + bars[3])           # |---

# --- 6. A range target that shadows an outer name of the same kind -------
# The proof is about the comprehension's own target, so an outer variable of
# the same name must not be consulted for it.  Here the outer `i` is a str
# and the comprehension's `i` is a `range` target, and the elements are ints.
#
# The outer binding is deliberately NOT printed back afterwards.  Python gives
# a comprehension its own scope, so `i` should still be "not an int" after the
# line below — and fastpy prints `4`, having emitted the comprehension inline
# and let its target clobber the enclosing name.  That is a real bug, but it
# is a *scoping* bug that predates this file and is unrelated to element-kind
# inference; asserting it here would make this regression fail for the wrong
# reason.  It is logged as BUG-COMPREHENSION-LEAKS-ITS-LOOP-VARIABLE and gets
# its own regression when it is fixed.
i = "not an int"
squares = [i * i for i in range(4)]
print(squares[3])                        # 9
