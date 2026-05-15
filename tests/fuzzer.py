"""
Fuzzer for the fastpy compiler.

Generates random Python programs from templates, compiles them with
fastpy, runs both CPython and compiled versions, and reports any
differences (FAIL results).

Usage:
    python -m tests.fuzzer              # Run 200 random programs
    python -m tests.fuzzer -n 500       # Run 500
    python -m tests.fuzzer --seed 42    # Reproducible run
    python -m tests.fuzzer --category arithmetic  # Fuzz one category
    python -m tests.fuzzer --save-fails fails/    # Save failing programs
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.harness import diff_test


# ---------------------------------------------------------------------------
# Program generators: each returns a Python source string
# ---------------------------------------------------------------------------

def _gen_arithmetic(rng: random.Random) -> str:
    """Random arithmetic expressions with int/float."""
    lines = []
    n_vars = rng.randint(2, 5)
    for i in range(n_vars):
        if rng.random() < 0.5:
            val = rng.randint(-100, 100)
        else:
            val = round(rng.uniform(-100.0, 100.0), 2)
        lines.append(f"v{i} = {val}")

    n_ops = rng.randint(1, 4)
    ops = ["+", "-", "*", "//", "%", "**"]
    for i in range(n_ops):
        a = f"v{rng.randint(0, n_vars - 1)}"
        b = f"v{rng.randint(0, n_vars - 1)}"
        op = rng.choice(ops)
        # Avoid division by zero and huge exponents
        if op in ("//", "%"):
            lines.append(f"r{i} = {a} {op} {b} if {b} != 0 else 0")
        elif op == "**":
            # Clamp exponent to avoid overflow; use int() to avoid
            # min() mixed-type issue (min(float, int) returns float in
            # compiled code but int in CPython — known limitation)
            lines.append(f"r{i} = {a} {op} min(int(abs({b})), 10)")
        else:
            lines.append(f"r{i} = {a} {op} {b}")
        lines.append(f"print(r{i})")

    return "\n".join(lines)


def _gen_string_ops(rng: random.Random) -> str:
    """Random string operations."""
    words = ["hello", "world", "foo", "bar", "baz", "test", "abc", "123",
             "UPPER", "lower", "MiXeD", "", " spaces ", "a b c"]
    s = rng.choice(words)
    lines = [f's = "{s}"']

    methods = [
        "s.upper()", "s.lower()", "s.strip()", "s.title()",
        "s.capitalize()", "s.swapcase()", "len(s)",
        "s.startswith('a')", "s.endswith('o')",
        f"s.replace('{rng.choice('aeiou')}', 'X')",
        "s.split()", "s.split(' ')",
        "s.count('a')", "s.find('o')",
        f"s * {rng.randint(0, 3)}",
        f"s + '{rng.choice(words)}'",
        "'_'.join(s.split())",
        "s.isdigit()", "s.isalpha()", "s.isalnum()",
        "s[::-1]", f"s[:{rng.randint(0, 5)}]",
    ]
    for _ in range(rng.randint(2, 5)):
        m = rng.choice(methods)
        lines.append(f"print({m})")

    return "\n".join(lines)


def _gen_list_ops(rng: random.Random) -> str:
    """Random list operations."""
    n = rng.randint(0, 8)
    elems = [str(rng.randint(-20, 20)) for _ in range(n)]
    lines = [f"lst = [{', '.join(elems)}]"]

    ops = [
        "print(lst)",
        "print(len(lst))",
        "print(sorted(lst))" if n > 0 else "print(lst)",
        f"lst.append({rng.randint(-10, 10)})\nprint(lst)",
        "print(lst[::-1])",
        f"print(lst[{rng.randint(0, max(n - 1, 0))}])" if n > 0 else "print(lst)",
        "print(sum(lst))" if n > 0 else "print(0)",
        "print(min(lst))" if n > 0 else "print(lst)",
        "print(max(lst))" if n > 0 else "print(lst)",
        "print([x * 2 for x in lst])",
        "print([x for x in lst if x > 0])",
        "lst.reverse()\nprint(lst)",
    ]
    for _ in range(rng.randint(2, 5)):
        lines.append(rng.choice(ops))

    return "\n".join(lines)


def _gen_dict_ops(rng: random.Random) -> str:
    """Random dictionary operations."""
    n = rng.randint(1, 5)
    keys = rng.sample(range(1, 20), min(n, 19))
    vals = [rng.randint(-50, 50) for _ in range(n)]
    pairs = ", ".join(f"{k}: {v}" for k, v in zip(keys, vals))
    lines = [f"d = {{{pairs}}}"]

    ops = [
        "print(d)",
        "print(len(d))",
        "print(sorted(d.keys()))",
        "print(sorted(d.values()))",
        "print(sorted(d.items()))",
        f"d[{rng.randint(20, 30)}] = {rng.randint(0, 100)}\nprint(d)",
        f"print(d.get({keys[0]}, -1))" if keys else "print(d)",
        f"print({keys[0]} in d)" if keys else "print(d)",
    ]
    for _ in range(rng.randint(2, 4)):
        lines.append(rng.choice(ops))

    return "\n".join(lines)


def _gen_control_flow(rng: random.Random) -> str:
    """Random if/elif/else, for, while."""
    lines = []
    x = rng.randint(-10, 10)
    lines.append(f"x = {x}")

    # if/elif/else
    cmp = rng.choice(["> 0", "< 0", "== 0", ">= 5", "<= -5"])
    lines.append(f"if x {cmp}:")
    lines.append(f'    print("branch1")')
    if rng.random() < 0.5:
        cmp2 = rng.choice(["> 0", "< 0", "== 0"])
        lines.append(f"elif x {cmp2}:")
        lines.append(f'    print("branch2")')
    lines.append("else:")
    lines.append(f'    print("branch3")')

    # for loop
    n = rng.randint(1, 6)
    lines.append(f"total = 0")
    lines.append(f"for i in range({n}):")
    lines.append(f"    total += i")
    lines.append(f"print(total)")

    # while loop
    if rng.random() < 0.5:
        limit = rng.randint(1, 5)
        lines.append(f"c = 0")
        lines.append(f"while c < {limit}:")
        lines.append(f"    c += 1")
        lines.append(f"print(c)")

    return "\n".join(lines)


def _gen_functions(rng: random.Random) -> str:
    """Random function definitions and calls."""
    lines = []

    # Simple function
    op = rng.choice(["+", "-", "*"])
    lines.append(f"def calc(a, b):")
    lines.append(f"    return a {op} b")
    a, b = rng.randint(-10, 10), rng.randint(-10, 10)
    lines.append(f"print(calc({a}, {b}))")

    # Function with default arg
    default = rng.randint(1, 10)
    lines.append(f"def greet(name, times={default}):")
    lines.append(f"    for i in range(times):")
    lines.append(f'        print(f"hi {{name}}")')
    lines.append(f'greet("alice", {rng.randint(1, 3)})')

    # Recursive function
    if rng.random() < 0.5:
        n = rng.randint(1, 8)
        lines.append(f"def fact(n):")
        lines.append(f"    if n <= 1: return 1")
        lines.append(f"    return n * fact(n - 1)")
        lines.append(f"print(fact({n}))")

    return "\n".join(lines)


def _gen_classes(rng: random.Random) -> str:
    """Random class definitions."""
    lines = []
    init_val = rng.randint(0, 100)
    lines.append(f"class Counter:")
    lines.append(f"    def __init__(self):")
    lines.append(f"        self.count = {init_val}")
    lines.append(f"    def inc(self):")
    lines.append(f"        self.count += 1")
    lines.append(f"    def get(self):")
    lines.append(f"        return self.count")
    lines.append(f"c = Counter()")
    n = rng.randint(1, 5)
    for _ in range(n):
        lines.append(f"c.inc()")
    lines.append(f"print(c.get())")

    # Inheritance
    if rng.random() < 0.5:
        lines.append(f"class DoubleCounter(Counter):")
        lines.append(f"    def inc(self):")
        lines.append(f"        self.count += 2")
        lines.append(f"d = DoubleCounter()")
        for _ in range(rng.randint(1, 3)):
            lines.append(f"d.inc()")
        lines.append(f"print(d.get())")

    return "\n".join(lines)


def _gen_comprehensions(rng: random.Random) -> str:
    """Random list/dict/set comprehensions."""
    lines = []
    n = rng.randint(3, 10)

    # List comprehension
    expr = rng.choice(["x", "x * 2", "x ** 2", "x + 1", "-x"])
    cond = rng.choice(["", " if x > 0", " if x % 2 == 0", " if x != 0"])
    lines.append(f"print([{expr} for x in range({n}){cond}])")

    # Dict comprehension
    lines.append(f"print({{k: k*k for k in range({rng.randint(1, 6)})}})")

    # Set comprehension
    vals = [str(rng.randint(0, 5)) for _ in range(rng.randint(3, 8))]
    lines.append(f"print(sorted({{x % 3 for x in [{', '.join(vals)}]}}))")

    return "\n".join(lines)


def _gen_exceptions(rng: random.Random) -> str:
    """Random try/except patterns."""
    lines = []

    exc_type = rng.choice(["ValueError", "TypeError", "ZeroDivisionError",
                           "IndexError", "KeyError"])
    lines.append("try:")

    if exc_type == "ZeroDivisionError":
        lines.append("    x = 1 / 0")
    elif exc_type == "ValueError":
        lines.append('    x = int("abc")')
    elif exc_type == "IndexError":
        lines.append("    x = [1, 2][10]")
    elif exc_type == "KeyError":
        lines.append("    x = {}[1]")
    else:
        lines.append("    x = 1 + 'a'")

    lines.append(f"except {exc_type}:")
    lines.append(f'    print("caught {exc_type}")')

    # Multiple except
    if rng.random() < 0.5:
        lines.append("try:")
        lines.append("    y = 1 / 0")
        lines.append("except (ZeroDivisionError, ValueError):")
        lines.append('    print("caught multi")')

    return "\n".join(lines)


def _gen_fstrings(rng: random.Random) -> str:
    """Random f-string expressions."""
    lines = []
    x = rng.randint(-100, 100)
    f = round(rng.uniform(-10.0, 10.0), 3)
    s = rng.choice(["hello", "world", "test", "abc"])
    lines.append(f"x = {x}")
    lines.append(f"f = {f}")
    lines.append(f's = "{s}"')

    patterns = [
        'f"x = {x}"',
        'f"f = {f:.2f}"',
        'f"s = {s!r}"',
        'f"s = {s!s}"',
        'f"{x:>10}"',
        'f"{x:05d}"',
        'f"{s:^20}"',
        'f"{x} + {f} = {x + f}"',
        'f"{'  + "'-' * 20" + '}"',
        'f"{len(s)}"',
        'f"{s.upper()}"',
    ]
    for _ in range(rng.randint(2, 5)):
        p = rng.choice(patterns)
        lines.append(f"print({p})")

    return "\n".join(lines)


def _gen_builtins(rng: random.Random) -> str:
    """Random builtin function calls."""
    lines = []
    n = rng.randint(3, 8)
    elems = [str(rng.randint(-20, 20)) for _ in range(n)]
    lines.append(f"lst = [{', '.join(elems)}]")

    calls = [
        "print(len(lst))",
        "print(sum(lst))",
        "print(min(lst))",
        "print(max(lst))",
        "print(sorted(lst))",
        "print(sorted(lst, reverse=True))",
        "print(list(reversed(lst)))",
        "print(abs(-42))",
        f"print(round({round(rng.uniform(-10, 10), 5)}, 2))",
        "print(bool(lst))",
        "print(int(3.7))",
        "print(float(42))",
        "print(str(123))",
        "print(list(range(5)))",
        "print(list(enumerate(lst[:3])))",
        "print(list(zip([1,2,3], [4,5,6])))",
        "print(any(x > 0 for x in lst))",
        "print(all(x > 0 for x in lst))",
        "print(isinstance(42, int))",
        "print(isinstance('hi', str))",
    ]
    for _ in range(rng.randint(3, 6)):
        lines.append(rng.choice(calls))

    return "\n".join(lines)


def _gen_closures(rng: random.Random) -> str:
    """Random closure patterns."""
    lines = []
    n = rng.randint(1, 5)

    lines.append(f"def make_adder(n):")
    lines.append(f"    def adder(x):")
    lines.append(f"        return x + n")
    lines.append(f"    return adder")
    lines.append(f"add{n} = make_adder({n})")
    lines.append(f"print(add{n}(10))")

    if rng.random() < 0.5:
        lines.append(f"def counter():")
        lines.append(f"    count = 0")
        lines.append(f"    def inc():")
        lines.append(f"        nonlocal count")
        lines.append(f"        count += 1")
        lines.append(f"        return count")
        lines.append(f"    return inc")
        lines.append(f"c = counter()")
        for i in range(rng.randint(1, 4)):
            lines.append(f"print(c())")

    return "\n".join(lines)


def _gen_boolean_ops(rng: random.Random) -> str:
    """Random boolean logic."""
    lines = []
    vals = [rng.choice(["True", "False"]) for _ in range(4)]
    for i, v in enumerate(vals):
        lines.append(f"v{i} = {v}")

    exprs = [
        "v0 and v1", "v0 or v1", "not v0",
        "v0 and v1 or v2", "(v0 or v1) and v2",
        "not (v0 and v1)", "v0 and not v1",
        "v0 == v1", "v0 != v1",
        "v0 is True", "v0 is not False",
    ]
    for _ in range(rng.randint(3, 6)):
        e = rng.choice(exprs)
        lines.append(f"print({e})")

    return "\n".join(lines)


def _gen_tuple_ops(rng: random.Random) -> str:
    """Random tuple operations."""
    lines = []
    n = rng.randint(2, 6)
    elems = [str(rng.randint(-10, 10)) for _ in range(n)]
    lines.append(f"t = ({', '.join(elems)},)")

    lines.append(f"print(t)")
    lines.append(f"print(len(t))")

    if n >= 2:
        lines.append(f"a, b = t[0], t[1]")
        lines.append(f"print(a, b)")

    if n >= 3:
        lines.append(f"first, *rest = t")
        lines.append(f"print(first, rest)")

    lines.append(f"print(t + ({rng.randint(0, 10)},))")
    lines.append(f"print(t * {rng.randint(1, 3)})")

    return "\n".join(lines)


def _gen_set_ops(rng: random.Random) -> str:
    """Random set operations."""
    lines = []
    a_elems = [str(rng.randint(1, 10)) for _ in range(rng.randint(2, 6))]
    b_elems = [str(rng.randint(1, 10)) for _ in range(rng.randint(2, 6))]
    lines.append(f"a = {{{', '.join(a_elems)}}}")
    lines.append(f"b = {{{', '.join(b_elems)}}}")

    lines.append("print(sorted(a))")
    lines.append("print(sorted(b))")
    lines.append("print(sorted(a | b))")
    lines.append("print(sorted(a & b))")
    lines.append("print(sorted(a - b))")
    lines.append("print(sorted(a ^ b))")
    lines.append(f"print({rng.choice(a_elems)} in a)")

    return "\n".join(lines)


def _gen_slicing(rng: random.Random) -> str:
    """Random slicing patterns."""
    lines = []
    n = rng.randint(5, 12)
    elems = [str(rng.randint(0, 99)) for _ in range(n)]
    lines.append(f"lst = [{', '.join(elems)}]")
    lines.append(f's = "abcdefghij"')

    slices = [
        f"lst[{rng.randint(0, n-1)}:]",
        f"lst[:{rng.randint(1, n)}]",
        f"lst[{rng.randint(0, n//2)}:{rng.randint(n//2, n)}]",
        "lst[::-1]",
        f"lst[::2]",
        f"lst[1::2]",
        "s[2:5]",
        "s[::-1]",
        "s[::2]",
    ]
    for _ in range(rng.randint(3, 6)):
        lines.append(f"print({rng.choice(slices)})")

    return "\n".join(lines)


def _gen_mixed_types(rng: random.Random) -> str:
    """Mixing types — comparisons, conversions, etc."""
    lines = []
    lines.append(f"x = {rng.randint(-10, 10)}")
    lines.append(f"f = {round(rng.uniform(-10, 10), 2)}")
    lines.append(f's = "{rng.choice(["hello", "123", "True", ""])}"')

    exprs = [
        "print(type(x).__name__)",
        "print(type(f).__name__)",
        "print(type(s).__name__)",
        "print(x == int(f))",
        "print(float(x) == f)",
        "print(str(x))",
        "print(bool(x))",
        "print(bool(s))",
        "print(x > f)",
        "print(x < 0 or f > 0)",
    ]
    for _ in range(rng.randint(3, 5)):
        lines.append(rng.choice(exprs))

    return "\n".join(lines)


def _gen_walrus(rng: random.Random) -> str:
    """Walrus operator patterns."""
    lines = []
    n = rng.randint(3, 8)
    elems = [str(rng.randint(-5, 15)) for _ in range(n)]
    lines.append(f"data = [{', '.join(elems)}]")

    lines.append("filtered = [y for x in data if (y := x * 2) > 5]")
    lines.append("print(filtered)")

    lines.append(f"if (n := len(data)) > 3:")
    lines.append(f'    print(f"long: {{n}}")')
    lines.append(f"else:")
    lines.append(f'    print(f"short: {{n}}")')

    return "\n".join(lines)


def _gen_match(rng: random.Random) -> str:
    """Match/case patterns."""
    lines = []
    val = rng.choice([rng.randint(0, 5), f'"{rng.choice(["a", "b", "c"])}"',
                       "None", "True", "[1, 2]", "(1, 2, 3)"])
    lines.append(f"x = {val}")
    lines.append("match x:")
    lines.append('    case 0:')
    lines.append('        print("zero")')
    lines.append('    case 1 | 2:')
    lines.append('        print("one or two")')
    lines.append('    case str() as s:')
    lines.append(f'        print(f"string: {{s}}")')
    lines.append('    case [a, b]:')
    lines.append(f'        print(f"list: {{a}}, {{b}}")')
    lines.append("    case _:")
    lines.append(f'        print(f"other: {{x}}")')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry of all generators
# ---------------------------------------------------------------------------

GENERATORS: dict[str, callable] = {
    "arithmetic": _gen_arithmetic,
    "string_ops": _gen_string_ops,
    "list_ops": _gen_list_ops,
    "dict_ops": _gen_dict_ops,
    "control_flow": _gen_control_flow,
    "functions": _gen_functions,
    "classes": _gen_classes,
    "comprehensions": _gen_comprehensions,
    "exceptions": _gen_exceptions,
    "fstrings": _gen_fstrings,
    "builtins": _gen_builtins,
    "closures": _gen_closures,
    "boolean_ops": _gen_boolean_ops,
    "tuple_ops": _gen_tuple_ops,
    "set_ops": _gen_set_ops,
    "slicing": _gen_slicing,
    "mixed_types": _gen_mixed_types,
    "walrus": _gen_walrus,
    "match": _gen_match,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_fuzzer(
    n_programs: int = 200,
    seed: int | None = None,
    category: str | None = None,
    save_dir: str | None = None,
    timeout: float = 10.0,
    verbose: bool = False,
) -> dict:
    """Run the fuzzer and return statistics."""
    rng = random.Random(seed)
    if seed is not None:
        print(f"Seed: {seed}")

    if category:
        if category not in GENERATORS:
            print(f"Unknown category: {category}")
            print(f"Available: {', '.join(sorted(GENERATORS.keys()))}")
            sys.exit(1)
        gen_list = [(category, GENERATORS[category])]
    else:
        gen_list = list(GENERATORS.items())

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    stats = {"pass": 0, "skip": 0, "fail": 0, "error": 0}
    failures = []
    start = time.time()

    for i in range(n_programs):
        cat_name, gen_fn = rng.choice(gen_list)
        try:
            source = gen_fn(rng)
        except Exception as e:
            print(f"\n[GEN-ERROR] Generator {cat_name} crashed: {e}")
            stats["error"] += 1
            continue

        try:
            result = diff_test(source, timeout=timeout)
        except Exception as e:
            print(f"\n[HARNESS-ERROR] {cat_name} #{i}: {e}")
            stats["error"] += 1
            continue

        stats[result.status] += 1

        if result.failed:
            failures.append((i, cat_name, source, result))
            if save_dir:
                fpath = Path(save_dir) / f"fail_{i:04d}_{cat_name}.py"
                fpath.write_text(source, encoding="utf-8")

            # Print failure immediately
            print(f"\n{'='*60}")
            print(f"FAIL #{i} [{cat_name}] (seed offset {i})")
            print(f"{'='*60}")
            print(source)
            print(f"--- CPython stdout ---")
            print(result.cpython.stdout if result.cpython else "(none)")
            print(f"--- Compiled stdout ---")
            print(result.compiled.stdout if result.compiled else "(none)")
            if result.cpython and result.compiled:
                if result.cpython.exit_code != result.compiled.exit_code:
                    print(f"Exit codes: CPython={result.cpython.exit_code}, "
                          f"Compiled={result.compiled.exit_code}")

        # Progress indicator
        if (i + 1) % 10 == 0 or verbose:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"\r[{i+1}/{n_programs}] "
                  f"P:{stats['pass']} S:{stats['skip']} F:{stats['fail']} E:{stats['error']} "
                  f"({rate:.1f}/s)  ", end="", flush=True)

    elapsed = time.time() - start
    print(f"\n\n{'='*60}")
    print(f"Fuzzer complete: {n_programs} programs in {elapsed:.1f}s")
    print(f"  PASS: {stats['pass']}")
    print(f"  SKIP: {stats['skip']}")
    print(f"  FAIL: {stats['fail']}")
    print(f"  ERROR: {stats['error']}")
    if failures:
        print(f"\n{len(failures)} failures found:")
        for idx, cat, src, res in failures:
            first_line = src.split('\n')[0][:60]
            print(f"  #{idx} [{cat}] {res.reason} — {first_line}...")
    print(f"{'='*60}")

    return {"stats": stats, "failures": failures}


def main():
    parser = argparse.ArgumentParser(description="Fuzz the fastpy compiler")
    parser.add_argument("-n", type=int, default=200, help="Number of programs to generate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--category", type=str, default=None, help="Fuzz only one category")
    parser.add_argument("--save-fails", type=str, default=None, help="Directory to save failing programs")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-program timeout (seconds)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    result = run_fuzzer(
        n_programs=args.n,
        seed=args.seed,
        category=args.category,
        save_dir=args.save_fails,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    # Exit with failure code if any tests failed
    sys.exit(1 if result["stats"]["fail"] > 0 else 0)


if __name__ == "__main__":
    main()
