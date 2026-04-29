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


def tuple_expr(max_size: int = 4) -> st.SearchStrategy[str]:
    """Generate tuple literals."""
    return st.lists(
        int_literal(),
        min_size=0,
        max_size=max_size,
    ).map(lambda items: f"({', '.join(items)}{',' if len(items) == 1 else ''})")


def set_expr(max_size: int = 4) -> st.SearchStrategy[str]:
    """Generate set literals (non-empty to avoid empty-dict ambiguity)."""
    return st.lists(
        int_literal(),
        min_size=1,
        max_size=max_size,
        unique=True,
    ).map(lambda items: "{" + ", ".join(items) + "}")


def list_comp_expr() -> st.SearchStrategy[str]:
    """Generate list comprehensions."""
    var = st.sampled_from(["i", "j", "k"])
    limit = st.integers(min_value=0, max_value=10)
    transform = st.sampled_from([
        "{v}", "{v} * 2", "{v} + 1", "{v} * {v}", "str({v})",
    ])
    has_filter = st.booleans()
    filter_expr = st.sampled_from([
        "{v} > 0", "{v} % 2 == 0", "{v} < 5", "{v} != 0",
    ])

    @st.composite
    def _make(draw):
        v = draw(var)
        n = draw(limit)
        t = draw(transform).replace("{v}", v)
        if draw(has_filter):
            f = draw(filter_expr).replace("{v}", v)
            return f"[{t} for {v} in range({n}) if {f}]"
        return f"[{t} for {v} in range({n})]"

    return _make()


def dict_comp_expr() -> st.SearchStrategy[str]:
    """Generate dict comprehensions."""
    var = st.sampled_from(["i", "j", "k"])
    limit = st.integers(min_value=0, max_value=8)

    @st.composite
    def _make(draw):
        v = draw(var)
        n = draw(limit)
        return f"{{{v}: {v} * {v} for {v} in range({n})}}"

    return _make()


def ternary_expr() -> st.SearchStrategy[str]:
    """Generate ternary (conditional) expressions."""
    @st.composite
    def _make(draw):
        cond = draw(comparison_expr())
        then_val = draw(int_literal())
        else_val = draw(int_literal())
        return f"({then_val} if {cond} else {else_val})"

    return _make()


def bool_expr() -> st.SearchStrategy[str]:
    """Generate boolean expressions with and/or/not."""
    op = st.sampled_from(["and", "or"])
    val = st.one_of(
        bool_literal(),
        int_literal(),
        comparison_expr(),
    )

    @st.composite
    def _make(draw):
        left = draw(val)
        right = draw(val)
        o = draw(op)
        use_not = draw(st.booleans())
        if use_not:
            return f"not ({left} {o} {right})"
        return f"({left} {o} {right})"

    return _make()


def string_method_expr() -> st.SearchStrategy[str]:
    """Generate string method calls."""
    method = st.sampled_from([
        ".upper()", ".lower()", ".strip()", ".title()",
        ".capitalize()", ".swapcase()",
    ])
    return st.tuples(string_literal(), method).map(
        lambda t: f"{t[0]}{t[1]}"
    )


def builtin_call_expr() -> st.SearchStrategy[str]:
    """Generate calls to builtin functions on lists."""
    @st.composite
    def _make(draw):
        items = draw(st.lists(int_literal(), min_size=1, max_size=8))
        lst = f"[{', '.join(items)}]"
        func = draw(st.sampled_from(["len", "sum", "min", "max", "sorted"]))
        return f"{func}({lst})"

    return _make()


def fstring_expr() -> st.SearchStrategy[str]:
    """Generate f-string expressions."""
    @st.composite
    def _make(draw):
        var = draw(varname())
        kind = draw(st.sampled_from(["plain", "format_int", "format_float"]))
        if kind == "format_int":
            return f'f"{{{var}:05d}}"'
        elif kind == "format_float":
            return f'f"{{{var}:.2f}}"'
        return f'f"val={{{var}}}"'

    return _make()


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


def try_except_stmt() -> st.SearchStrategy[str]:
    """Generate a try/except statement that exercises exception handling."""
    @st.composite
    def _make(draw):
        kind = draw(st.sampled_from([
            "zero_div", "index", "key", "type",
        ]))
        if kind == "zero_div":
            divisor = draw(st.sampled_from([0, 1, 2, -1]))
            return (
                f"try:\n"
                f"    result = 10 / {divisor}\n"
                f"    print(result)\n"
                f"except ZeroDivisionError:\n"
                f"    print('caught ZeroDivisionError')"
            )
        elif kind == "index":
            idx = draw(st.integers(min_value=-5, max_value=5))
            return (
                f"try:\n"
                f"    lst = [1, 2, 3]\n"
                f"    print(lst[{idx}])\n"
                f"except IndexError:\n"
                f"    print('caught IndexError')"
            )
        elif kind == "key":
            key = draw(st.sampled_from(['"a"', '"b"', '"z"']))
            return (
                f'try:\n'
                f'    d = {{"a": 1, "b": 2}}\n'
                f'    print(d[{key}])\n'
                f'except KeyError:\n'
                f"    print('caught KeyError')"
            )
        else:  # type error
            op = draw(st.sampled_from([
                '"hello" + 5', '[1,2] + 3', '"abc" - 1',
            ]))
            return (
                f"try:\n"
                f"    result = {op}\n"
                f"except TypeError:\n"
                f"    print('caught TypeError')"
            )

    return _make()


def augmented_assign_stmt() -> st.SearchStrategy[str]:
    """Generate augmented assignment statements."""
    var = varname()
    op = st.sampled_from(["+=", "-=", "*="])
    val = int_literal()
    return st.tuples(var, op, val).map(
        lambda t: f"{t[0]} {t[1]} {t[2]}"
    )


def list_operation_stmt() -> st.SearchStrategy[str]:
    """Generate list operations (append, extend, insert, pop)."""
    @st.composite
    def _make(draw):
        var = draw(st.sampled_from(["lst", "items", "data"]))
        op = draw(st.sampled_from(["append", "pop", "reverse", "sort"]))
        if op == "append":
            val = draw(int_literal())
            return f"{var}.append({val})"
        elif op == "pop":
            return f"if {var}: {var}.pop()"
        elif op == "reverse":
            return f"{var}.reverse()"
        else:
            return f"{var}.sort()"

    return _make()


def for_list_stmt() -> st.SearchStrategy[str]:
    """Generate for loop over a list variable."""
    @st.composite
    def _make(draw):
        var = draw(st.sampled_from(["lst", "items", "data"]))
        elem = draw(st.sampled_from(["x", "item", "elem"]))
        action = draw(st.sampled_from([
            f"print({elem})",
            f"print({elem} * 2)",
            f"total += {elem}",
        ]))
        if "total" in action:
            return f"total = 0\nfor {elem} in {var}:\n    {action}\nprint(total)"
        return f"for {elem} in {var}:\n    {action}"

    return _make()


def tuple_unpack_stmt() -> st.SearchStrategy[str]:
    """Generate tuple unpacking assignments."""
    @st.composite
    def _make(draw):
        n = draw(st.integers(min_value=2, max_value=4))
        vars_ = ["a", "b", "c", "d"][:n]
        vals = [str(draw(st.integers(min_value=-10, max_value=10)))
                for _ in range(n)]
        return f"{', '.join(vars_)} = {', '.join(vals)}\nprint({', '.join(vars_)})"

    return _make()


def swap_stmt() -> st.SearchStrategy[str]:
    """Generate variable swap."""
    @st.composite
    def _make(draw):
        v1 = draw(st.sampled_from(["x", "a", "p"]))
        v2 = draw(st.sampled_from(["y", "b", "q"]))
        val1 = draw(int_literal())
        val2 = draw(int_literal())
        return (
            f"{v1} = {val1}\n{v2} = {val2}\n"
            f"{v1}, {v2} = {v2}, {v1}\n"
            f"print({v1}, {v2})"
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


@st.composite
def valid_program_with_containers(draw) -> str:
    """Generate programs that exercise container operations."""
    stmts: list[str] = []

    # Initialize a list
    items = draw(st.lists(int_literal(), min_size=1, max_size=8))
    stmts.append(f"lst = [{', '.join(items)}]")
    stmts.append("print(lst)")

    # Perform operations
    n_ops = draw(st.integers(min_value=1, max_value=4))
    for _ in range(n_ops):
        op = draw(st.sampled_from([
            "print_sorted", "print_len", "print_sum", "print_min",
            "print_max", "append", "comp", "builtin",
        ]))
        if op == "print_sorted":
            stmts.append("print(sorted(lst))")
        elif op == "print_len":
            stmts.append("print(len(lst))")
        elif op == "print_sum":
            stmts.append("print(sum(lst))")
        elif op == "print_min":
            stmts.append("if lst: print(min(lst))")
        elif op == "print_max":
            stmts.append("if lst: print(max(lst))")
        elif op == "append":
            val = draw(int_literal())
            stmts.append(f"lst.append({val})")
        elif op == "comp":
            stmts.append(draw(list_comp_expr()))
            stmts.append(f"print({stmts.pop()})")
        elif op == "builtin":
            stmts.append(f"print({draw(builtin_call_expr())})")

    stmts.append("print(lst)")
    return "\n".join(stmts)


@st.composite
def valid_program_with_strings(draw) -> str:
    """Generate programs that exercise string operations."""
    stmts: list[str] = []

    # Initialize strings
    s = draw(string_literal())
    stmts.append(f"s = {s}")

    n_ops = draw(st.integers(min_value=1, max_value=5))
    for _ in range(n_ops):
        op = draw(st.sampled_from([
            "upper", "lower", "strip", "len", "split",
            "replace", "find", "count", "startswith",
            "mul", "in", "slice",
        ]))
        if op == "upper":
            stmts.append("print(s.upper())")
        elif op == "lower":
            stmts.append("print(s.lower())")
        elif op == "strip":
            stmts.append("print(s.strip())")
        elif op == "len":
            stmts.append("print(len(s))")
        elif op == "split":
            stmts.append("print(s.split())")
        elif op == "replace":
            old = draw(st.sampled_from(["a", "e", "o", " "]))
            stmts.append(f'print(s.replace("{old}", "X"))')
        elif op == "find":
            ch = draw(st.sampled_from(["a", "e", "i", "o"]))
            stmts.append(f'print(s.find("{ch}"))')
        elif op == "count":
            ch = draw(st.sampled_from(["a", "e", "i", "o"]))
            stmts.append(f'print(s.count("{ch}"))')
        elif op == "startswith":
            pref = draw(st.sampled_from(["", "a", "he", "th"]))
            stmts.append(f'print(s.startswith("{pref}"))')
        elif op == "mul":
            n = draw(st.integers(min_value=0, max_value=5))
            stmts.append(f"print(s * {n})")
        elif op == "in":
            sub = draw(st.sampled_from(["a", "the", "xyz"]))
            stmts.append(f'print("{sub}" in s)')
        elif op == "slice":
            i = draw(st.integers(min_value=0, max_value=5))
            j = draw(st.integers(min_value=0, max_value=10))
            stmts.append(f"print(s[{i}:{j}])")

    stmts.append("print(s)")
    return "\n".join(stmts)


@st.composite
def valid_program_with_dicts(draw) -> str:
    """Generate programs that exercise dict operations."""
    stmts: list[str] = []

    # Initialize a dict
    keys = draw(st.lists(
        st.sampled_from(["a", "b", "c", "d", "e", "x", "y", "z"]),
        min_size=1, max_size=5, unique=True,
    ))
    vals = [str(draw(st.integers(min_value=-100, max_value=100)))
            for _ in keys]
    pairs = ", ".join(f'"{k}": {v}' for k, v in zip(keys, vals))
    stmts.append(f"d = {{{pairs}}}")

    n_ops = draw(st.integers(min_value=1, max_value=4))
    for _ in range(n_ops):
        op = draw(st.sampled_from([
            "print_keys", "print_values", "print_items",
            "get", "in", "len", "set", "pop",
        ]))
        if op == "print_keys":
            stmts.append("print(sorted(d.keys()))")
        elif op == "print_values":
            stmts.append("print(sorted(d.values()))")
        elif op == "print_items":
            stmts.append("print(sorted(d.items()))")
        elif op == "get":
            k = draw(st.sampled_from(keys + ["missing"]))
            stmts.append(f'print(d.get("{k}", -1))')
        elif op == "in":
            k = draw(st.sampled_from(keys + ["missing"]))
            stmts.append(f'print("{k}" in d)')
        elif op == "len":
            stmts.append("print(len(d))")
        elif op == "set":
            k = draw(st.sampled_from(keys + ["new"]))
            v = draw(st.integers(min_value=-100, max_value=100))
            stmts.append(f'd["{k}"] = {v}')
        elif op == "pop":
            k = draw(st.sampled_from(keys))
            stmts.append(f'if "{k}" in d: print(d.pop("{k}"))')

    stmts.append("print(sorted(d.items()))")
    return "\n".join(stmts)


@st.composite
def valid_program_with_exceptions(draw) -> str:
    """Generate programs that exercise exception handling."""
    stmts: list[str] = []

    n_tries = draw(st.integers(min_value=1, max_value=3))
    for _ in range(n_tries):
        stmts.append(draw(try_except_stmt()))

    stmts.append('print("done")')
    return "\n".join(stmts)


@st.composite
def valid_program_comprehensive(draw) -> str:
    """Generate programs combining multiple feature categories."""
    stmts: list[str] = []

    # Variable initializations with various types
    stmts.append(f"x = {draw(int_literal())}")
    stmts.append(f"y = {draw(int_literal())}")
    stmts.append(f"s = {draw(string_literal())}")
    items = draw(st.lists(int_literal(), min_size=1, max_size=5))
    stmts.append(f"lst = [{', '.join(items)}]")

    # Mix of statements
    n_body = draw(st.integers(min_value=2, max_value=6))
    for _ in range(n_body):
        stmt = draw(st.one_of(
            print_stmt(),
            st.just("print(len(lst))"),
            st.just("print(sum(lst))"),
            st.just("print(s.upper())"),
            st.just("print(len(s))"),
            st.just("print(sorted(lst))"),
            if_stmt(body_depth=0),
            for_stmt(body_depth=0),
            try_except_stmt(),
            augmented_assign_stmt(),
        ))
        stmts.append(stmt)

    stmts.append("print(x, y)")
    stmts.append("print(lst)")
    return "\n".join(stmts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _indent(text: str, spaces: int = 4) -> str:
    """Indent every line of text."""
    return textwrap.indent(text, " " * spaces)
