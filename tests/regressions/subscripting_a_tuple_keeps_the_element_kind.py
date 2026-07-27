"""An element read out of a tuple has the kind the tuple recorded.

BUG-TUPLE-SUBSCRIPT-ELEM-KIND-LOST.

`_infer_type_tag`'s "subscript on a name" arm asked whether the name's
kind was `VKind.LIST` before believing its `elem_type`.  A tuple
subscripts to an element in exactly the same way and carries exactly the
same fact, so `node[1]` on a `tuple:mixed` parameter matched no arm at
all and fell through to `_llvm_type_tag`, which reports the loaded i64
as an `int`:

    def walk(node):
        for stmt in node[1]:      # segfault
            print(stmt)

    program = ("block", [1, 2])
    walk(program)

`for` picks its loop shape from that answer.  `mixed` routes to the
runtime-dispatched loop; `int` routes to the native list loop, which
calls `list_length` on what is actually an FpyValue.  Writing the very
same program with a list literal — `program = ["block", [1, 2]]` — was
correct throughout, which is the asymmetry that found this.

`_LIST_LIKE = (VKind.LIST, VKind.TUPLE, VKind.DEQUE)` had been sitting a
few lines below `VKind` since it was introduced, with a comment saying
it groups the kinds that "support iteration, append, len", and had never
been referenced once.  This is its first use.

The bug only became reachable when `_csa_build_var_types` learned to
record tuples at all (BUG-TUPLE-RETURN-SEGFAULTS) — before that no tuple
ever arrived here carrying an element kind, so the missing arm could not
fire.  A producer that starts telling the truth wakes every consumer
that was relying on it staying quiet.
"""


# ── The reported shape: a tuple parameter, subscripted, then iterated ────

def walk(node):
    out = []
    for stmt in node[1]:
        out.append(stmt)
    return out


program = ("block", [1, 2, 3])
print(walk(program))


# ── The list spelling of the same thing, which was always correct ────────

lprogram = ["block", [1, 2, 3]]
print(walk(lprogram))


# ── Recursion through a nested tuple, the pattern that reported it ───────
# This is `test_self_compile_codegen_subset` reduced: a class whose
# dispatch reads `node[0]`, recurses over `node[1]`, and is handed a
# module-level tuple.

class Gen:
    def __init__(self):
        self.output = []

    def generate(self, node):
        kind = node[0]
        if kind == "block":
            for stmt in node[1]:
                self.generate(stmt)
        else:
            self.output.append(kind)


tree = ("block", [
    ("assign", "x"),
    ("print", "y"),
    ("block", [("assign", "z")]),
])

g = Gen()
g.generate(tree)
print(g.output)


# ── Element kinds other than "mixed" ─────────────────────────────────────

def second(t):
    return t[1]


pair_of_lists = ([1, 2], [3, 4, 5])
pair_of_strs = ("ab", "cde")
pair_of_floats = (1.5, 2.5)
pair_of_dicts = ({"a": 1}, {"b": 2, "c": 3})

print(second(pair_of_lists), len(second(pair_of_lists)))
print(second(pair_of_strs), len(second(pair_of_strs)))
print(second(pair_of_floats), second(pair_of_floats) + 1.0)
print(len(second(pair_of_dicts)), second(pair_of_dicts)["b"])


# ── Iterating each of those, which is where the wrong kind crashed ───────

def total_len(t):
    n = 0
    for item in t[0]:
        n += 1
    return n


print(total_len(pair_of_lists), total_len(pair_of_strs))


# ── A tuple read directly, without passing through a parameter ───────────

nested = ("head", [10, 20, 30])
acc = 0
for v in nested[1]:
    acc += v
print(nested[0], acc)

print("end")
