"""A rebound `len` or `range` is not evidence that a name holds an int.

`_csa_provably_int_names` proves a module-level name is a machine int so that
`_duf_select_abi` has the positive evidence it requires for the bare ABI --
without it, `add(i, 1)` in a counter loop lost the bare ABI and every call
boxed and unboxed a tagged FpyValue, which cost ~9x.

Two of its arms trust a builtin by name: `len(...)` is an int, and
`for i in range(...)` binds one. Both were guarded with
`not in self._user_functions`, which is the wrong question asked of the wrong
object -- `_user_functions` is still empty when the predicate runs during
`_csa_build_var_types`, so the guard answered "not shadowed" for every program
ever compiled and the arms were effectively unguarded.

A program that defines its own `len` therefore proved `n = len(L)` to be an
int when it is a str, `sink` took the bare `i64` ABI on that evidence, and the
str pointer came back reinterpreted:

    def len(x):
        return "zz"
    n = len([1, 2, 3])
    print(sink(n))      # 140699144869504, should be zz

which is BUG-UNTYPED-PARAM-BARE-ABI reintroduced through the evidence rather
than through the ABI rule. The shadowing is now read off the AST, covering
`def`, `class`, `import ... as` and plain assignment, and covering the whole
tree rather than just module level: a nested `def len` cannot actually shadow
the module-level builtin, but declining costs one refinement while trusting it
costs a pointer read as an integer.

The final two cases pin the fast path the predicate exists to enable -- an
unshadowed `len` and `range` must still prove their names -- so a future guard
that over-declines fails here rather than silently regressing 9x.
"""


def sink(v):
    return v


def sink_len(v):
    return len(v)


# ── `len` rebound to return a str: `n` is not an int ──

def len(x):                                    # noqa: A001
    return "zz"


L = [1, 2, 3]
n = len(L)
print(sink(n))


# ── `range` rebound to yield strs: `i` is not an int ──

def range(n):                                  # noqa: A001
    return ["ab", "cde"]


for i in range(2):
    print(sink_len(i))
