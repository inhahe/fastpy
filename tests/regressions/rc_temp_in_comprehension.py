"""Owned temps created inside a comprehension body must be released per
iteration, in the body itself — not left pending for the enclosing statement.

BUG-DECREF-DOES-NOT-DOMINATE (comprehension facet).

A comprehension is lowered to a real loop: a cond block, a body block, an
incr block and an end block. Model-2 refcounting registers every freshly
allocated (+1) value as an owned temp and releases the whole pending set at
the next statement boundary. For a comprehension that boundary is *after*
the loop, in the end block — and the end block is reached from the cond
block, not from the body. So a temp defined in the body:

  * does not dominate its own release  -> "Instruction does not dominate all
    uses!", the module is rejected by the LLVM verifier and nothing compiles
    at all; and
  * even if it did, the pending entry only names the value from the *last*
    iteration, so every earlier iteration would leak.

This is not the conditional-expression case, where the fix is to rebuild the
temp as a phi at the merge point: a loop body runs N times and there is no
single merged value to release. The correct fix is a per-iteration flush at
the end of the body, before the back-edge. That is safe because every
container store retains: `fpy_list_append` and `fastpy_dict_set_fv` both
incref what they store, so the container holds its own reference and the
body's +1 is genuinely surplus once the element is in.

A filter (`if` clause) forks the body into keep/skip paths that both reach
the incr block, so the release is emitted on *both* arms (they are mutually
exclusive, and the fork block dominates each).

Regression coverage below: element expression allocates; filter condition
allocates; both allocate; a generator expression consumed by `str.join`
(the shape that broke self-compilation of `compiler/pipeline.py`); dict
comprehensions with allocating keys and values, with and without a filter;
a multi-generator comprehension; and long loops so a double free crashes
and a leak grows without bound.
"""


def element_allocates():
    nums = [1, 2, 3, 4, 5]
    a = [str(n) for n in nums]
    print(",".join(a))


def condition_allocates():
    words = ["alpha", "beta", "gamma", "delta"]
    b = [w for w in words if str(len(w)) == "5"]
    print(",".join(b))


def both_allocate():
    words = ["alpha", "beta", "gamma", "delta"]
    c = [w.upper() for w in words if w.upper().startswith("A")]
    print(",".join(c))


def genexp_into_join():
    # The exact construct that made compiler/pipeline.py emit invalid IR:
    #   ", ".join(str(o) for o in self.operands)
    nums = [1, 2, 3, 4, 5]
    print(", ".join(str(n) for n in nums))


def dict_comp_allocating():
    nums = [1, 2, 3, 4, 5]
    d = {str(n): str(n * 2) for n in nums}
    print(d["3"])


def dict_comp_filtered():
    words = ["alpha", "beta", "gamma", "delta"]
    e = {w: str(len(w)) for w in words if len(w) > 4}
    print(e["alpha"])


def multi_generator():
    # Two generators, allocating element expression and an allocating filter.
    # NOTE: iterated over a list *of lists*; a nested comprehension whose
    # outer iterable is a flat list of ints mis-tags the outer variable —
    # see BUG-NESTED-LISTCOMP-OUTER-ELEM-TAG, unrelated to refcounting.
    rows = [[1, 2, 3], [4, 5, 6]]
    f = [str(y) + "!" for row in rows for y in row if str(y) != "5"]
    print(len(f), f[0], f[-1])


def repeated():
    # 200 iterations: a double free aborts, a leak grows the heap without
    # bound. `len(g)` is checked every time so the list contents stay live.
    nums = [1, 2, 3, 4, 5]
    total = 0
    i = 0
    while i < 200:
        g = [str(n) + "x" for n in nums if n != 3]
        h = {str(n): str(n) + "y" for n in nums if n != 2}
        total = total + len(g) + len(h)
        i = i + 1
    print(total)


def set_comp_and_genexp_builtins():
    # Set comprehensions and generator expressions are both lowered through
    # _emit_list_comprehension, so they inherit the same per-iteration flush.
    nums = [1, 2, 3]
    print(len({str(n) for n in nums}))
    print(any(str(n) == "2" for n in nums))
    print(all(str(n) != "9" for n in nums))
    print(sorted(str(n) for n in nums))


def crossed_with_conditional_arms():
    # The two facets of BUG-DECREF-DOES-NOT-DOMINATE meeting each other: a
    # comprehension inside a conditional-expression arm (phi rebuild wrapping a
    # per-iteration flush), a conditional expression inside a comprehension
    # element (per-iteration flush wrapping a phi rebuild), and an `and`/`or`
    # short circuit inside a filter.
    nums = [1, 2, 3]
    words = ["aa", "bb"]
    a = [str(n) for n in nums] if nums else []
    b = [str(n) if n > 1 else "lo" for n in nums]
    c = [w for w in words if w and str(len(w)) == "2"]
    d = {str(n): n for n in nums} if nums else {}
    print(len(a), len(b), len(c), len(d))


def in_statement_contexts():
    # A comprehension in a return, as a call argument, nested in an element,
    # inside a try, and inside a loop that breaks — each ends the enclosing
    # statement at a different place.
    nums = [1, 2, 3]
    words = ["aa", "bb"]

    def build():
        return [str(n) for n in nums]

    print(len(build()))
    print(len(list(str(n) for n in nums)))
    print(len([[str(n) for n in nums] for _w in words]))
    try:
        print(len([str(n) for n in nums]))
    except ValueError:
        print("no")
    for _w in words:
        p = [str(n) for n in nums if n != 2]
        if len(p) == 2:
            break
    print(len(p))
    print(", ".join([f"<{n}>" for n in nums]).upper())


element_allocates()
condition_allocates()
both_allocate()
genexp_into_join()
dict_comp_allocating()
dict_comp_filtered()
multi_generator()
repeated()
set_comp_and_genexp_builtins()
crossed_with_conditional_arms()
in_statement_contexts()
