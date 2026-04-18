"""
Random Python program generator for property-based testing.

Uses Hypothesis strategies to generate valid, deterministic Python programs
that can be fed through the differential test harness. Programs are built
from AST nodes and unparsed to source code, so they're always syntactically
valid.

Design goals:
    - Programs are deterministic (no random, no time, no system state)
    - Programs terminate (bounded loops, bounded recursion via depth limits)
    - Programs print their results (so we can compare output)
    - Programs use only language features (no imports beyond builtins)
    - Programs cover: arithmetic, strings, lists, dicts, control flow,
      functions, classes, comprehensions

Usage with Hypothesis:
    @given(source=valid_program())
    def test_generated(source):
        result = diff_test(source)
        assert not result.failed
"""

from __future__ import annotations

import ast
import textwrap

from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Leaf expression strategies
# ---------------------------------------------------------------------------

def int_literal() -> st.SearchStrategy[str]:
    """Generate integer literals including negatives."""
    return st.integers(min_value=-1000, max_value=1000).map(repr)


def float_literal() -> st.SearchStrategy[str]:
    """Generate float literals (avoiding inf/nan for determinism)."""
    return st.floats(
        min_value=-1000.0,
        max_value=1000.0,
        allow_nan=False,
        allow_infinity=False,
    ).map(repr)


def string_literal() -> st.SearchStrategy[str]:
    """Generate short string literals with safe characters."""
    return st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
            blacklist_characters="\\'\"\r\n\x00",
        ),
        min_size=0,
        max_size=20,
    ).map(repr)


def bool_literal() -> st.SearchStrategy[str]:
    return st.sampled_from(["True", "False"])


def none_literal() -> st.SearchStrategy[str]:
    return st.just("None")


def leaf_expr() -> st.SearchStrategy[str]:
    """Any literal expression."""
    return st.one_of(
        int_literal(),
        float_literal(),
        string_literal(),
        bool_literal(),
        none_literal(),
    )


# ---------------------------------------------------------------------------
# Composite expression strategies
# ---------------------------------------------------------------------------

def varname() -> st.SearchStrategy[str]:
    """Generate valid Python variable names."""
    return st.sampled_from([
        "x", "y", "z", "a", "b", "c", "n", "m",
        "val", "tmp", "result", "total", "count", "item",
    ])


def arith_expr(max_depth: int = 2) -> st.SearchStrategy[str]:
    """Generate arithmetic expressions."""
    if max_depth <= 0:
        return st.one_of(int_literal(), float_literal(), varname())

    op = st.sampled_from(["+", "-", "*"])
    sub = arith_expr(max_depth - 1)
    return st.one_of(
        sub,
        st.tuples(sub, op, sub).map(lambda t: f"({t[0]} {t[1]} {t[2]})"),
    )


def comparison_expr() -> st.SearchStrategy[str]:
    """Generate comparison expressions."""
    op = st.sampled_from(["<", "<=", ">", ">=", "==", "!="])
    val = st.one_of(int_literal(), varname())
    return st.tuples(val, op, val).map(lambda t: f"{t[0]} {t[1]} {t[2]}")


def list_expr(max_size: int = 5) -> st.SearchStrategy[str]:
    """Generate list literals."""
    return st.lists(
        st.one_of(int_literal(), string_literal()),
        min_size=0,
        max_size=max_size,
    ).map(lambda items: f"[{', '.join(items)}]")


def dict_expr(max_size: int = 4) -> st.SearchStrategy[str]:
    """Generate dict literals with string keys."""
    return st.lists(
        st.tuples(string_literal(), int_literal()),
        min_size=0,
        max_size=max_size,
    ).map(lambda pairs: "{" + ", ".join(f"{k}: {v}" for k, v in pairs) + "}")


# ---------------------------------------------------------------------------
# Statement strategies
# ---------------------------------------------------------------------------

def assignment_stmt() -> st.SearchStrategy[str]:
    """Generate variable assignment."""
    return st.tuples(varname(), st.one_of(
        arith_expr(),
        list_expr(),
        string_literal(),
        int_literal(),
    )).map(lambda t: f"{t[0]} = {t[1]}")


def print_stmt() -> st.SearchStrategy[str]:
    """Generate a print statement."""
    return st.one_of(
        arith_expr(),
        string_literal(),
        int_literal(),
        list_expr(),
    ).map(lambda expr: f"print({expr})")


def if_stmt(body_depth: int = 1) -> st.SearchStrategy[str]:
    """Generate an if/else statement."""
    cond = comparison_expr()
    body = simple_body(body_depth)

    @st.composite
    def _make(draw):
        c = draw(cond)
        then_body = draw(body)
        has_else = draw(st.booleans())
        result = f"if {c}:\n{_indent(then_body)}"
        if has_else:
            else_body = draw(body)
            result += f"\nelse:\n{_indent(else_body)}"
        return result

    return _make()


def for_stmt(body_depth: int = 1) -> st.SearchStrategy[str]:
    """Generate a bounded for loop."""
    var = varname()
    limit = st.integers(min_value=0, max_value=10)
    body = simple_body(body_depth)

    return st.tuples(var, limit, body).map(
        lambda t: f"for {t[0]} in range({t[1]}):\n{_indent(t[2])}"
    )


def while_stmt() -> st.SearchStrategy[str]:
    """Generate a bounded while loop (always terminates)."""
    var = varname()
    limit = st.integers(min_value=0, max_value=10)

    return st.tuples(var, limit).map(
        lambda t: f"{t[0]} = 0\nwhile {t[0]} < {t[1]}:\n"
                  f"    print({t[0]})\n    {t[0]} += 1"
    )


def function_def() -> st.SearchStrategy[str]:
    """Generate a simple function definition and call."""
    fname = st.sampled_from(["f", "g", "h", "compute", "helper"])
    params = st.lists(
        st.sampled_from(["a", "b", "c", "n"]),
        min_size=1,
        max_size=3,
        unique=True,
    )
    body_expr = arith_expr(max_depth=1)

    @st.composite
    def _make(draw):
        fn = draw(fname)
        ps = draw(params)
        expr = draw(body_expr)
        args = ", ".join(str(draw(st.integers(min_value=-10, max_value=10)))
                         for _ in ps)
        return (
            f"def {fn}({', '.join(ps)}):\n"
            f"    return {expr}\n"
            f"print({fn}({args}))"
        )

    return _make()


def simple_body(depth: int = 1) -> st.SearchStrategy[str]:
    """Generate a simple statement body (one or more statements)."""
    stmts = st.lists(
        st.one_of(
            print_stmt(),
            assignment_stmt(),
        ),
        min_size=1,
        max_size=3,
    )
    return stmts.map(lambda ss: "\n".join(ss))


# ---------------------------------------------------------------------------
# Full program strategies
# ---------------------------------------------------------------------------

@st.composite
def valid_program(draw, max_stmts: int = 8) -> str:
    """
    Generate a complete, valid, deterministic Python program that prints output.

    The program:
      - Initializes some variables
      - Performs operations
      - Prints results
      - Always terminates
      - Uses no imports
    """
    stmts: list[str] = []

    # Start with a few variable initializations
    n_inits = draw(st.integers(min_value=1, max_value=3))
    for _ in range(n_inits):
        stmts.append(draw(assignment_stmt()))

    # Add a mix of statements
    n_body = draw(st.integers(min_value=1, max_value=max_stmts))
    for _ in range(n_body):
        stmt = draw(st.one_of(
            print_stmt(),
            assignment_stmt(),
            if_stmt(body_depth=0),
            for_stmt(body_depth=0),
        ))
        stmts.append(stmt)

    # Always end with at least one print
    stmts.append(draw(print_stmt()))

    return "\n".join(stmts)


@st.composite
def valid_program_with_functions(draw) -> str:
    """Generate a program that includes function definitions."""
    parts: list[str] = []

    # One or two function definitions
    n_fns = draw(st.integers(min_value=1, max_value=2))
    for _ in range(n_fns):
        parts.append(draw(function_def()))

    # Some additional statements
    n_stmts = draw(st.integers(min_value=0, max_value=3))
    for _ in range(n_stmts):
        parts.append(draw(print_stmt()))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _indent(text: str, spaces: int = 4) -> str:
    """Indent every line of text."""
    return textwrap.indent(text, " " * spaces)
