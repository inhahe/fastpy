"""Indexing a list of lists twice keeps the inner element's kind.

BUG-BIGINT-COMPARES-BY-POINTER, the nested-container half.

`_get_list_elem_type` had an arm for a *slice* subscript (`words[1:]`
propagates the source's element type) but none for an *index* subscript.
So `outer[0]`'s element type fell through to the INT default, and
`outer[0][0]` read a heap element back as its own address:

    inner = [2 ** 85]
    outer = [inner, inner]
    outer[0][0] == inner[0]      # was False, CPython says True

The tell was that the identical read through a temporary was correct all
along — `x = outer[0]; x[0] == inner[0]` answered True — because binding
to a name goes through `self.variables`, which records the full nested
element type. Only the double subscript, which never touches a variable,
had nowhere to ask.

Printing is right in every case here, because `print` uses the runtime
tag that `FpyList.items` (an `FpyValue*`) has carried all along. Only the
statically-dispatched operations — `==`, arithmetic, `len` — were wrong,
which is why this hid for so long: nothing crashes and nothing prints
oddly, the answers are just false.

Every section below reads an inner element in a way that depends on its
*tag* rather than its bits, and pairs the direct double subscript with
the through-a-temporary form that already worked, so a regression in
either is visible.
"""


# ── BigInt elements: the original report ─────────────────────────────────

inner = [2 ** 85]
outer = [inner, inner]

x = outer[0]
print(x[0] == inner[0])
print(outer[0][0] == inner[0])
print(outer[1][0] == 2 ** 85)
print(outer[0][0])
print(outer[0][0] == outer[1][0])


# ── str elements ─────────────────────────────────────────────────────────

words = ["alpha", "beta"]
grid = [words, words]

print(grid[0][0], grid[1][1])
print(len(grid[0][0]), len(grid[1][1]))
print(grid[0][0] == "alpha", grid[1][1] == "beta")
print(grid[0][1].upper(), grid[0][0] + "!")


# ── float elements: arithmetic reads the tag, not just the bits ──────────

fs = [1.5, 2.5]
fgrid = [fs, fs]

print(fgrid[0][0] + 1, fgrid[1][1] * 2)
print(fgrid[0][0] == 1.5, fgrid[0][1] > fgrid[0][0])


# ── int elements must be unchanged ───────────────────────────────────────

ns = [1, 2, 3]
ngrid = [ns, ns]

print(ngrid[0][0] + 1, ngrid[1][2], len(ngrid[0]))
print(ngrid[0][0] == 1, sum(ngrid[1]))


# ── Literal nesting, with no intermediate name at all ────────────────────

lit = [[2 ** 90, 2 ** 91], [2 ** 92]]
print(lit[0][0] == 2 ** 90, lit[1][0] == 2 ** 92)
print(len(lit), len(lit[0]), len(lit[1]))
print(lit[0][1])

slit = [["one", "two"], ["three"]]
print(slit[0][1], len(slit[0][1]), slit[1][0] == "three")


# ── Three levels deep ────────────────────────────────────────────────────

deep = [[["x", "yy"]]]
print(deep[0][0][1], len(deep[0][0][1]), deep[0][0][0] == "x")


# ── Iteration, which reaches elements by a different route ───────────────

total = 0
for row in grid:
    for w in row:
        total = total + len(w)
print(total)

for row in outer:
    print(row[0] == 2 ** 85)

print("end")
