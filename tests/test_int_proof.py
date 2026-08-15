"""Unit tests for the "is this provably an int?" prover in codegen.

`tests/regressions/set_elem_kind_proof.py` checks the same prover end to end,
by compiling programs and diffing their output against CPython. That is the
test that matters, but it can only observe the prover through whatever the
generated code happens to do — and the interesting half of a conservative
analysis is the half where it *declines* to answer, which usually looks
identical from the outside to answering correctly. A program whose set is
proven int and one whose set stays dynamic print the same thing; only their
speed differs, and speed is not something a differential test can assert.

So these tests call `_set_elem_tag` and `_expr_is_provably_int` directly, and
most of them assert a refusal. The asymmetry is the point: a False here costs
a slower loop, while a wrong True costs a segfault
(BUG-FOR-DICT-KEY-KIND-GUESSED), so the refusals are the safety property and
deserve to be pinned individually rather than inferred from a passing program.
"""

from __future__ import annotations

import ast

import pytest

from compiler.codegen import CodeGen


def _prover(src: str) -> CodeGen:
    """A CodeGen with just enough state for the analysis methods.

    The prover reads `_csa_root_tree` and nothing else, so a full compile is
    not needed — and not wanted, since it would make these tests fail for
    reasons that have nothing to do with the prover.
    """
    cg = CodeGen.__new__(CodeGen)
    cg._csa_root_tree = ast.parse(src)
    return cg


def _scope_of_binding(cg: CodeGen, name: str):
    """The scope the assignment to `name` lives in."""
    for n in ast.walk(cg._csa_root_tree):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == name):
            return cg._scope_of(n)
    return None


def _set_tag(src: str, name: str = "s"):
    cg = _prover(src)
    scope = _scope_of_binding(cg, name)
    node = ast.Name(id=name, ctx=ast.Load())
    # Codegen passes the real `for ... in s` node, which is in the tree and so
    # has a scope of its own; a fabricated Name has none, so register it.
    cg._scope_map()[id(node)] = scope
    return cg._set_elem_tag(node)


# ── Shapes the prover must prove ────────────────────────────────────────

PROVABLE = [
    ("while counter", """
s = set()
i = 0
while i < 100000:
    s.add(i)
    i = i + 1
"""),
    ("augassign counter", """
s = set()
i = 0
while i < 10:
    s.add(i)
    i += 1
"""),
    ("for over range", """
s = set()
for i in range(10):
    s.add(i)
"""),
    ("arithmetic on a counter", """
s = set()
i = 0
while i < 10:
    s.add(i * 2 + 1)
    i = i + 1
"""),
    ("len() of anything", """
s = set()
for w in words:
    s.add(len(w))
"""),
    ("int literals", """
s = set()
s.add(1)
s.add(2)
"""),
    ("int set literal binding", """
s = {1, 2, 3}
"""),
    ("adds then a non-adding method", """
s = set()
i = 0
while i < 10:
    s.add(i)
    i = i + 1
s.discard(3)
"""),
    ("two independent int counters", """
s = set()
i = 0
j = 5
while i < 10:
    s.add(i)
    s.add(j)
    i = i + 1
    j = j + 2
"""),
    ("inside a function", """
def f(n):
    s = set()
    i = 0
    while i < n:
        s.add(i)
        i = i + 1
    return s
"""),
    ("a dead function's parameter must not poison it", """
def unused(i):
    return i

def live():
    s = set()
    i = 0
    while i < 4:
        s.add(i)
        i = i + 1
    return s
"""),
]


@pytest.mark.parametrize("label,src", PROVABLE, ids=[c[0] for c in PROVABLE])
def test_int_set_is_proven(label, src):
    assert _set_tag(src) == "int"


# ── Shapes the prover must refuse ───────────────────────────────────────
#
# Each of these would be a miscompile if it answered "int".

UNPROVABLE = [
    ("str elements", """
s = set()
s.add("a")
s.add("b")
"""),
    ("float counter", """
s = set()
i = 0.0
while i < 10:
    s.add(i)
    i = i + 1.0
"""),
    ("true division yields a float", """
s = set()
i = 0
while i < 10:
    s.add(i / 2)
    i = i + 1
"""),
    ("str() of an int is a str", """
s = set()
for i in range(10):
    s.add(str(i))
"""),
    ("a parameter has no proven kind here", """
def f(x):
    s = set()
    s.add(x)
    return s
"""),
    ("update() brings in unproven elements", """
s = set()
s.add(1)
s.update(other)
"""),
    ("|= brings in unproven elements", """
s = set()
s.add(1)
s |= other
"""),
    ("mixed set literal", """
s = {1, "a"}
"""),
    ("True is not an int", """
s = set()
s.add(True)
"""),
    ("rebound to an opaque call", """
s = set()
s.add(1)
s = make_set()
"""),
    ("counter from an opaque call", """
s = set()
i = compute()
while i < 10:
    s.add(i)
    i = i + 1
"""),
    ("counter defined only in terms of itself", """
s = set()
while i < 10:
    s.add(i)
    i = i + 1
"""),
    ("counter bound by tuple unpacking", """
s = set()
i, j = 0, 1
while i < 10:
    s.add(i)
    i = i + 1
"""),
    ("counter declared global", """
def f():
    global i
    s = set()
    i = 0
    while i < 10:
        s.add(i)
        i = i + 1
    return s
"""),
    ("counter deleted", """
s = set()
i = 0
s.add(i)
del i
"""),
    ("for over an unknown iterable", """
s = set()
for i in stuff:
    s.add(i)
"""),
    ("an empty set proves nothing", """
s = set()
"""),
    ("an empty set literal proves nothing", """
s = set()
t = {1}
"""),
]


@pytest.mark.parametrize("label,src", UNPROVABLE,
                         ids=[c[0] for c in UNPROVABLE])
def test_unprovable_set_is_refused(label, src):
    assert _set_tag(src) is None


# ── Scoping: same name, different variable ──────────────────────────────

_TWO_SCOPES = """
def a():
    s = set()
    i = 0
    while i < 10:
        s.add(i)
        i = i + 1
    return s

def b():
    s = set()
    i = "k"
    s.add(i)
    return s
"""


def test_same_name_in_two_functions_is_two_variables():
    """`i` is an int in `a` and a str in `b`; neither may answer for the other.

    This is BUG-UNCALLED-FN-PARAM-NAME-POISONS-A-CALLED-ONE in miniature: the
    lookup walks the module, so without scoping the first `i` it finds wins.
    """
    cg = _prover(_TWO_SCOPES)
    fns = {f.name: f for f in cg._csa_root_tree.body}
    answers = {}
    for name, fn in fns.items():
        node = ast.Name(id="s", ctx=ast.Load())
        cg._scope_map()[id(node)] = fn
        answers[name] = cg._set_elem_tag(node)
    assert answers == {"a": "int", "b": None}


# ── The int prover on its own ───────────────────────────────────────────

_COUNTER_SRC = """
i = 0
j = "x"
k = 1.5
n = len(stuff)
while i < 10:
    i = i + 1
"""

INT_EXPRS = ["1", "-3", "i", "i + 1", "i * 2 - 1", "len(q)", "abs(i)",
             "ord(c)", "hash(c)", "i % 7", "i // 2", "i << 1", "n"]
NON_INT_EXPRS = ["1.5", "'a'", "True", "j", "k", "i / 2", "str(i)", "i + j",
                 "undefined_name", "f(i)", "[1]", "i + k"]


@pytest.mark.parametrize("expr", INT_EXPRS)
def test_expr_is_provably_int(expr):
    cg = _prover(_COUNTER_SRC)
    assert cg._expr_is_provably_int(ast.parse(expr, mode="eval").body, None)


@pytest.mark.parametrize("expr", NON_INT_EXPRS)
def test_expr_is_not_provably_int(expr):
    cg = _prover(_COUNTER_SRC)
    assert not cg._expr_is_provably_int(ast.parse(expr, mode="eval").body, None)


# ── _proven_tag must not launder ignorance into "int" ───────────────────

def test_proven_tag_refuses_unknown_kinds():
    """`ValueType._to_tag()` maps UNKNOWN and FVALUE to the string "int", and
    falls back to "int" for anything missing from its table. `_proven_tag`
    exists so a caller that stamps the answer into an FpyValue as a literal
    tag cannot be handed an admission of ignorance that looks like a fact."""
    from compiler.codegen import ValueType, VKind

    cg = CodeGen.__new__(CodeGen)
    assert cg._proven_tag(None) is None
    assert cg._proven_tag(ValueType(VKind.UNKNOWN)) is None
    assert cg._proven_tag(ValueType(VKind.FVALUE)) is None
    assert cg._proven_tag(ValueType(VKind.MIXED)) is None
    assert cg._proven_tag(ValueType(VKind.INT)) == "int"
    assert cg._proven_tag(ValueType(VKind.STR)) == "str"
    # A list of ints keeps its element tag; a list of unknowns must not claim
    # "list:int", which would be the same lie one level down.
    assert cg._proven_tag(ValueType(VKind.LIST, ValueType(VKind.INT))) == "list:int"
    assert cg._proven_tag(ValueType(VKind.LIST, ValueType(VKind.UNKNOWN))) == "list"
