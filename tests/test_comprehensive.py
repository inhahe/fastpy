"""
Comprehensive test suite: unifies all existing tests and adds new tiers.

Tiers (in order of increasing scope):

1. **Regression tests** — existing tests/regressions/ and tests/programs/
   (auto-collected by conftest.py, not repeated here)

2. **Differential tests** — existing test_differential.py inline tests
   (not repeated here)

3. **Pyperformance benchmarks** — existing test_full_suite.py
   (not repeated here)

4. **Stdlib algorithm tests** — existing test_full_suite.py
   (not repeated here)

5. **Stdlib compilation tests** — NEW: compile pure-Python stdlib modules
   with inlined test suites exercising them, then diff output against CPython.
   This is the "compile stdlib fallback implementations" idea.

6. **CPython test suite (adapted)** — NEW: adapted portions of CPython's
   own test_*.py suite compiled with fastpy and diffed.

7. **Self-compilation test** — NEW: compile the fastpy compiler itself
   (or meaningful subsets) and verify it produces working output.

Run:
    pytest tests/test_comprehensive.py -v                   # everything
    pytest tests/test_comprehensive.py -k stdlib_compiled   # just stdlib compilation
    pytest tests/test_comprehensive.py -k cpython_tests     # adapted CPython tests
    pytest tests/test_comprehensive.py -k self_compile      # self-compilation
    pytest tests/test_comprehensive.py -k django            # Django test patterns
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from compiler.pipeline import compile_source, compile_file, CompileResult
from tests.harness import diff_test, run_cpython, run_executable, DiffResult, RunResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cpython_file(file_path: Path, timeout: float = 60.0) -> RunResult:
    """Run a Python source file under CPython."""
    try:
        proc = subprocess.run(
            [sys.executable, str(file_path)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return RunResult(
            stdout=proc.stdout, stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return RunResult(stdout="", stderr="Timed out", exit_code=-1, timed_out=True)


def _diff_test_source(source: str, timeout: float = 30.0) -> DiffResult:
    """Differential test a source string (compile + compare to CPython)."""
    return diff_test(source, timeout=timeout)


def _compile_and_diff_file(file_path: Path, timeout: float = 60.0) -> DiffResult:
    """Compile a .py file with fastpy, run both, compare outputs."""
    cpython_result = _run_cpython_file(file_path, timeout)
    if cpython_result.timed_out:
        return DiffResult(status="skip", reason="Timed out under CPython",
                          cpython=cpython_result)

    compile_result = compile_file(file_path)
    if not compile_result.success:
        return DiffResult(status="skip", reason="Compiler can't compile this yet",
                          cpython=cpython_result, compile_result=compile_result)

    assert compile_result.executable is not None
    compiled_result = run_executable(compile_result.executable, timeout)

    differences: list[str] = []
    if cpython_result.stdout != compiled_result.stdout:
        differences.append("stdout differs")
    if cpython_result.exit_code != compiled_result.exit_code:
        differences.append(f"exit code: CPython={cpython_result.exit_code}, "
                          f"Compiled={compiled_result.exit_code}")
    cpython_has_err = bool(cpython_result.stderr.strip())
    compiled_has_err = bool(compiled_result.stderr.strip())
    if cpython_has_err != compiled_has_err:
        differences.append("stderr presence differs")

    if differences:
        return DiffResult(status="fail", reason="; ".join(differences),
                          cpython=cpython_result, compiled=compiled_result,
                          compile_result=compile_result)
    return DiffResult(status="pass", reason="Output matches CPython",
                      cpython=cpython_result, compiled=compiled_result,
                      compile_result=compile_result)


# ===========================================================================
# TIER 5: Stdlib Compilation Tests
#
# Each test inlines a pure-Python stdlib module (or its key algorithms) and
# exercises it with a test harness that produces deterministic output.
# The program is compiled with fastpy and its output is diffed against CPython.
# ===========================================================================

# These are self-contained programs that inline stdlib module implementations
# and run tests against them — the "compile stdlib fallback" approach.
STDLIB_COMPILED_TESTS = {

    # ── bisect ──────────────────────────────────────────────────────────
    "bisect": textwrap.dedent("""\
        def bisect_right(a, x, lo=0, hi=None):
            if lo < 0:
                raise ValueError('lo must be non-negative')
            if hi is None:
                hi = len(a)
            while lo < hi:
                mid = (lo + hi) // 2
                if x < a[mid]:
                    hi = mid
                else:
                    lo = mid + 1
            return lo

        def bisect_left(a, x, lo=0, hi=None):
            if lo < 0:
                raise ValueError('lo must be non-negative')
            if hi is None:
                hi = len(a)
            while lo < hi:
                mid = (lo + hi) // 2
                if a[mid] < x:
                    lo = mid + 1
                else:
                    hi = mid
            return lo

        def insort_right(a, x, lo=0, hi=None):
            lo = bisect_right(a, x, lo, hi)
            a.insert(lo, x)

        def insort_left(a, x, lo=0, hi=None):
            lo = bisect_left(a, x, lo, hi)
            a.insert(lo, x)

        # Tests
        data = [1, 3, 5, 7, 9, 11, 13]
        print(bisect_left(data, 5))
        print(bisect_right(data, 5))
        print(bisect_left(data, 6))
        print(bisect_right(data, 6))
        print(bisect_left(data, 0))
        print(bisect_right(data, 14))
        lst = []
        for x in [5, 2, 8, 1, 9, 3, 7]:
            insort_right(lst, x)
        print(lst)
        lst2 = []
        for x in [5, 2, 8, 1, 9, 3, 7]:
            insort_left(lst2, x)
        print(lst2)
    """),

    # ── heapq ───────────────────────────────────────────────────────────
    "heapq": textwrap.dedent("""\
        def _siftdown(heap, startpos, pos):
            newitem = heap[pos]
            while pos > startpos:
                parentpos = (pos - 1) // 2
                parent = heap[parentpos]
                if newitem < parent:
                    heap[pos] = parent
                    pos = parentpos
                else:
                    break
            heap[pos] = newitem

        def _siftup(heap, pos):
            endpos = len(heap)
            startpos = pos
            newitem = heap[pos]
            childpos = 2 * pos + 1
            while childpos < endpos:
                rightpos = childpos + 1
                if rightpos < endpos and not heap[childpos] < heap[rightpos]:
                    childpos = rightpos
                heap[pos] = heap[childpos]
                pos = childpos
                childpos = 2 * pos + 1
            heap[pos] = newitem
            _siftdown(heap, startpos, pos)

        def heappush(heap, item):
            heap.append(item)
            _siftdown(heap, 0, len(heap) - 1)

        def heappop(heap):
            lastelt = heap.pop()
            if heap:
                returnitem = heap[0]
                heap[0] = lastelt
                _siftup(heap, 0)
                return returnitem
            return lastelt

        def heapify(x):
            n = len(x)
            i = n // 2 - 1
            while i >= 0:
                _siftup(x, i)
                i = i - 1

        # Tests
        h = []
        for val in [5, 3, 8, 1, 9, 2, 7, 4, 6]:
            heappush(h, val)
        result = []
        while h:
            result.append(heappop(h))
        print(result)

        data = [9, 5, 2, 7, 1, 8, 3]
        heapify(data)
        result2 = []
        while data:
            result2.append(heappop(data))
        print(result2)
    """),

    # ── statistics ──────────────────────────────────────────────────────
    "statistics": textwrap.dedent("""\
        def mean(data):
            n = len(data)
            if n == 0:
                raise ValueError('mean requires at least one data point')
            total = 0.0
            for x in data:
                total = total + x
            return total / n

        def median(data):
            n = len(data)
            if n == 0:
                raise ValueError('no median for empty data')
            s = sorted(data)
            if n % 2 == 1:
                return s[n // 2]
            else:
                i = n // 2
                return (s[i - 1] + s[i]) / 2.0

        def variance(data):
            n = len(data)
            if n < 2:
                raise ValueError('variance requires at least two data points')
            m = mean(data)
            total = 0.0
            for x in data:
                d = x - m
                total = total + d * d
            return total / (n - 1)

        def stdev(data):
            v = variance(data)
            return v ** 0.5

        # Tests
        d = [2, 4, 4, 4, 5, 5, 7, 9]
        print(mean(d))
        print(median(d))
        print(median([1, 3, 5]))
        print(median([1, 3, 5, 7]))
        print(round(variance(d), 6))
        print(round(stdev(d), 6))
    """),

    # ── collections.Counter (simplified) ────────────────────────────────
    "counter": textwrap.dedent("""\
        class Counter:
            def __init__(self, iterable=None):
                self._data = {}
                if iterable is not None:
                    for item in iterable:
                        if item in self._data:
                            self._data[item] = self._data[item] + 1
                        else:
                            self._data[item] = 1

            def most_common(self, n=None):
                items = []
                for k in self._data:
                    items.append((k, self._data[k]))
                # Sort by count descending, then by key
                # Simple bubble sort for portability
                for i in range(len(items)):
                    for j in range(i + 1, len(items)):
                        if items[j][1] > items[i][1]:
                            items[i], items[j] = items[j], items[i]
                if n is None:
                    return items
                return items[:n]

            def __getitem__(self, key):
                if key in self._data:
                    return self._data[key]
                return 0

        # Tests
        c = Counter("abracadabra")
        print(c["a"])
        print(c["b"])
        print(c["z"])
        mc = c.most_common(3)
        for item, count in mc:
            print(item, count)
    """),

    # ── functools (partial, reduce) ─────────────────────────────────────
    "functools_core": textwrap.dedent("""\
        def reduce(function, iterable, initial=None):
            it = iter(iterable)
            if initial is None:
                value = next(it)
            else:
                value = initial
            for element in it:
                value = function(value, element)
            return value

        class partial:
            def __init__(self, func, *args):
                self.func = func
                self.args = args
            def __call__(self, *more_args):
                all_args = list(self.args)
                for a in more_args:
                    all_args.append(a)
                return self.func(*all_args)

        # Tests
        def add(a, b):
            return a + b

        print(reduce(add, [1, 2, 3, 4, 5]))
        print(reduce(add, [1, 2, 3, 4, 5], 10))

        add5 = partial(add, 5)
        print(add5(3))
        print(add5(10))

        def mul(a, b):
            return a * b
        print(reduce(mul, [1, 2, 3, 4, 5]))
    """),

    # ── colorsys ────────────────────────────────────────────────────────
    "colorsys": textwrap.dedent("""\
        def rgb_to_hsv(r, g, b):
            maxc = max(r, g, b)
            minc = min(r, g, b)
            rangec = maxc - minc
            v = maxc
            if minc == maxc:
                return 0.0, 0.0, v
            s = rangec / maxc
            rc = (maxc - r) / rangec
            gc = (maxc - g) / rangec
            bc = (maxc - b) / rangec
            if r == maxc:
                h = bc - gc
            elif g == maxc:
                h = 2.0 + rc - bc
            else:
                h = 4.0 + gc - rc
            h = (h / 6.0) % 1.0
            return h, s, v

        def hsv_to_rgb(h, s, v):
            if s == 0.0:
                return v, v, v
            i = int(h * 6.0)
            f = (h * 6.0) - i
            p = v * (1.0 - s)
            q = v * (1.0 - s * f)
            t = v * (1.0 - s * (1.0 - f))
            i = i % 6
            if i == 0:
                return v, t, p
            if i == 1:
                return q, v, p
            if i == 2:
                return p, v, t
            if i == 3:
                return p, q, v
            if i == 4:
                return t, p, v
            if i == 5:
                return v, p, q
            return v, v, v

        # Tests
        h, s, v = rgb_to_hsv(0.2, 0.4, 0.6)
        print(round(h, 4), round(s, 4), round(v, 4))
        r, g, b = hsv_to_rgb(h, s, v)
        print(round(r, 4), round(g, 4), round(b, 4))
        print(rgb_to_hsv(1.0, 0.0, 0.0))
        print(rgb_to_hsv(0.0, 1.0, 0.0))
        print(rgb_to_hsv(0.0, 0.0, 1.0))
        print(hsv_to_rgb(0.0, 0.0, 0.5))
    """),

    # ── graphlib (topological sort) ─────────────────────────────────────
    "graphlib_topo": textwrap.dedent("""\
        def topological_sort(graph):
            in_degree = {}
            for node in graph:
                if node not in in_degree:
                    in_degree[node] = 0
                for dep in graph[node]:
                    if dep not in in_degree:
                        in_degree[dep] = 0
                    in_degree[dep] = in_degree[dep] + 1

            queue = []
            for node in in_degree:
                if in_degree[node] == 0:
                    queue.append(node)
            queue.sort()  # deterministic order

            result = []
            while queue:
                node = queue.pop(0)
                result.append(node)
                if node in graph:
                    deps = list(graph[node])
                    deps.sort()
                    for dep in deps:
                        in_degree[dep] = in_degree[dep] - 1
                        if in_degree[dep] == 0:
                            queue.append(dep)
                            queue.sort()

            if len(result) != len(in_degree):
                raise ValueError("cycle detected")
            return result

        # Tests
        g = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        print(topological_sort(g))
        g2 = {"x": ["y", "z"], "y": ["w"], "z": ["w"], "w": []}
        print(topological_sort(g2))
        g3 = {"a": [], "b": ["a"], "c": ["a", "b"]}
        print(topological_sort(g3))
    """),

    # ── contextlib (suppress, contextmanager pattern) ───────────────────
    "contextlib_suppress": textwrap.dedent("""\
        class suppress:
            def __init__(self, *exceptions):
                self._exceptions = exceptions
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is not None:
                    for e in self._exceptions:
                        if exc_type == e or (isinstance(exc_type, type) and issubclass(exc_type, e)):
                            return True
                return False

        # Tests
        with suppress(FileNotFoundError):
            raise FileNotFoundError("no file")
        print("after suppress FileNotFoundError")

        with suppress(ValueError, TypeError):
            raise TypeError("bad type")
        print("after suppress TypeError")

        with suppress(ValueError):
            print("no exception raised")
        print("done")
    """),
}


# Known xfail reasons for stdlib tests
_STDLIB_XFAILS: dict[str, str] = {
    "contextlib_suppress": "context manager __exit__ exception type matching not fully supported",
    "counter": "string character iteration + dict with mixed value types causes segfault",
    "functools_core": "*args (variadic positional arguments) not supported",
}


@pytest.mark.parametrize(
    "module_name",
    sorted(STDLIB_COMPILED_TESTS.keys()),
    ids=sorted(STDLIB_COMPILED_TESTS.keys()),
)
def test_stdlib_compiled(module_name: str):
    """Compile an inlined stdlib module + tests and diff against CPython."""
    if module_name in _STDLIB_XFAILS:
        pytest.xfail(_STDLIB_XFAILS[module_name])
    source = STDLIB_COMPILED_TESTS[module_name]
    result = _diff_test_source(source, timeout=30.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())


# ===========================================================================
# TIER 6: Adapted CPython Test Suite
#
# Selections from CPython's test suite adapted to be self-contained programs
# that print results (no unittest framework dependency). These test the same
# semantics CPython tests verify, but in a format the differential harness
# can handle.
# ===========================================================================

CPYTHON_ADAPTED_TESTS = {

    # ── test_list (adapted) ─────────────────────────────────────────────
    "test_list": textwrap.dedent("""\
        # Adapted from CPython Lib/test/test_list.py
        a = [0, 1, 2, 3, 4]
        a[1:3] = [10, 20, 30]
        print(a)
        a[2:4] = []
        print(a)
        a[1:1] = [99, 98, 97]
        print(a)

        # list.sort
        b = [3, 1, 4, 1, 5, 9, 2, 6]
        b.sort()
        print(b)
        b.sort(reverse=True)
        print(b)

        # list comprehension
        c = [x * x for x in range(10)]
        print(c)

        # list multiplication
        d = [0] * 5
        print(d)
        e = [1, 2] * 3
        print(e)

        # list.count, list.index
        f = [1, 2, 3, 2, 1, 2]
        print(f.count(2))
        print(f.index(3))

        # list.reverse
        g = [1, 2, 3, 4, 5]
        g.reverse()
        print(g)

        # list.copy
        h = [1, [2, 3], 4]
        h2 = h.copy()
        print(h2)
        print(h == h2)

        # nested list operations
        matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        flat = []
        for row in matrix:
            for x in row:
                flat.append(x)
        print(flat)
    """),

    # ── test_dict (adapted) ─────────────────────────────────────────────
    "test_dict": textwrap.dedent("""\
        # Adapted from CPython Lib/test/test_dict.py
        d = {"a": 1, "b": 2, "c": 3}
        print(sorted(d.keys()))
        print(sorted(d.values()))
        print(sorted(d.items()))

        # dict.update
        d.update({"b": 20, "d": 4})
        print(sorted(d.items()))

        # dict.pop
        v = d.pop("b")
        print(v)
        print("b" in d)

        # dict.get with default
        print(d.get("x", -1))
        print(d.get("a", -1))

        # dict.setdefault
        d.setdefault("e", 5)
        d.setdefault("a", 99)  # should not change existing
        print(d["e"])
        print(d["a"])

        # dict comprehension
        squares = {x: x*x for x in range(6)}
        print(sorted(squares.items()))

        # dict iteration
        keys = []
        for k in squares:
            keys.append(k)
        print(sorted(keys))
    """),

    # ── test_str (adapted) ──────────────────────────────────────────────
    "test_str": textwrap.dedent("""\
        # Adapted from CPython Lib/test/test_string.py
        s = "Hello, World!"
        print(s.upper())
        print(s.lower())
        print(s.split(", "))
        print(s.replace("World", "Python"))
        print(s.startswith("Hello"))
        print(s.endswith("!"))
        print(s.find("World"))
        print(s.find("xyz"))
        print(s.count("l"))
        print(s.strip())
        print("  spaces  ".strip())
        print("xxxhelloxxx".strip("x"))
        print("-".join(["a", "b", "c"]))
        print("hello world".title())
        print("hello world".capitalize())
        print("123".isdigit())
        print("abc".isalpha())
        print("abc123".isalnum())
        print(len(s))

        # f-strings
        name = "World"
        n = 42
        print(f"Hello, {name}! The answer is {n}.")
        print(f"{n:05d}")
        print(f"{3.14159:.2f}")
    """),

    # ── test_tuple (adapted) ────────────────────────────────────────────
    "test_tuple": textwrap.dedent("""\
        t = (1, 2, 3, 4, 5)
        print(t[0])
        print(t[-1])
        print(t[1:3])
        print(len(t))
        print(3 in t)
        print(6 in t)
        print(t.count(3))
        print(t.index(4))
        print(t + (6, 7))
        print(t * 2)

        # tuple unpacking
        a, b, c = (10, 20, 30)
        print(a, b, c)
        x, *rest = (1, 2, 3, 4, 5)
        print(x, rest)
        *init, last = (1, 2, 3, 4, 5)
        print(init, last)

        # nested tuples
        nested = ((1, 2), (3, 4), (5, 6))
        for a, b in nested:
            print(a + b)
    """),

    # ── test_set (adapted) ──────────────────────────────────────────────
    "test_set": textwrap.dedent("""\
        s = {3, 1, 4, 1, 5, 9, 2, 6}
        print(sorted(s))
        print(len(s))
        print(4 in s)
        print(7 in s)

        s.add(7)
        print(7 in s)
        s.discard(4)
        print(4 in s)

        a = {1, 2, 3, 4}
        b = {3, 4, 5, 6}
        print(sorted(a | b))
        print(sorted(a & b))
        print(sorted(a - b))
        print(sorted(a ^ b))

        # set from list
        words = ["hello", "world", "hello", "python", "world"]
        unique = sorted(set(words))
        print(unique)
    """),

    # ── test_generators (adapted) ───────────────────────────────────────
    "test_generators": textwrap.dedent("""\
        # Basic generator
        def count(n):
            i = 0
            while i < n:
                yield i
                i = i + 1

        print(list(count(5)))

        # Generator expression
        squares = list(x*x for x in range(6))
        print(squares)

        # Fibonacci generator
        def fib():
            a, b = 0, 1
            while True:
                yield a
                a, b = b, a + b

        f = fib()
        result = []
        for i in range(10):
            result.append(next(f))
        print(result)

        # Generator with return
        def gen_with_return():
            yield 1
            yield 2
            return

        print(list(gen_with_return()))

        # Chained generators
        def chain(*iterables):
            for it in iterables:
                for x in it:
                    yield x

        print(list(chain([1, 2], [3, 4], [5])))

        # Generator as filter
        def evens(it):
            for x in it:
                if x % 2 == 0:
                    yield x

        print(list(evens(range(10))))
    """),

    # ── test_exceptions (adapted) ───────────────────────────────────────
    "test_exceptions": textwrap.dedent("""\
        # Basic try/except
        try:
            x = 1 / 0
        except ZeroDivisionError:
            print("caught ZeroDivisionError")

        # Multiple except
        def safe_int(s):
            try:
                return int(s)
            except ValueError:
                return None
            except TypeError:
                return None

        print(safe_int("42"))
        print(safe_int("abc"))

        # try/except/else/finally
        def div(a, b):
            try:
                result = a / b
            except ZeroDivisionError:
                print("division by zero")
                return None
            else:
                print("success")
                return result
            finally:
                print("finally")

        print(div(10, 2))
        print(div(10, 0))

        # Raise and catch custom message
        try:
            raise ValueError("custom error")
        except ValueError as e:
            print(str(e))

        # Nested try
        try:
            try:
                raise TypeError("inner")
            except TypeError as e:
                print("caught inner:", e)
                raise ValueError("outer") from None
        except ValueError as e:
            print("caught outer:", e)
    """),

    # ── test_closures (adapted) ─────────────────────────────────────────
    "test_closures": textwrap.dedent("""\
        # Basic closure
        def make_adder(n):
            def add(x):
                return x + n
            return add

        add5 = make_adder(5)
        add10 = make_adder(10)
        print(add5(3))
        print(add10(3))

        # Closure over mutable (via list)
        def make_counter():
            count = [0]
            def increment():
                count[0] = count[0] + 1
                return count[0]
            return increment

        counter = make_counter()
        print(counter())
        print(counter())
        print(counter())

        # Closure in loop
        funcs = []
        for i in range(5):
            def f(x, i=i):
                return x + i
            funcs.append(f)
        print([fn(10) for fn in funcs])

        # Nested closures
        def outer(x):
            def middle(y):
                def inner(z):
                    return x + y + z
                return inner
            return middle

        print(outer(1)(2)(3))
    """),

    # ── test_classes_oop (adapted) ──────────────────────────────────────
    "test_classes_oop": textwrap.dedent("""\
        # Inheritance
        class Animal:
            def __init__(self, name):
                self.name = name
            def speak(self):
                return "..."

        class Dog(Animal):
            def speak(self):
                return "Woof!"

        class Cat(Animal):
            def speak(self):
                return "Meow!"

        animals = [Dog("Rex"), Cat("Whiskers"), Dog("Buddy")]
        for a in animals:
            print(a.name, a.speak())

        # Properties (via methods)
        class Circle:
            def __init__(self, radius):
                self._radius = radius
            def area(self):
                return 3.14159 * self._radius * self._radius
            def circumference(self):
                return 2 * 3.14159 * self._radius

        c = Circle(5)
        print(round(c.area(), 2))
        print(round(c.circumference(), 2))

        # Class with __repr__/__str__ style
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y
            def distance_to(self, other):
                dx = self.x - other.x
                dy = self.y - other.y
                return (dx * dx + dy * dy) ** 0.5

        p1 = Point(0, 0)
        p2 = Point(3, 4)
        print(p1.distance_to(p2))

        # Multiple inheritance (simple diamond)
        class Base:
            def method(self):
                return "Base"

        class Left(Base):
            def method(self):
                return "Left"

        class Right(Base):
            pass

        class Child(Left, Right):
            pass

        print(Child().method())
    """),
}


# Known xfail reasons for CPython adapted tests
_CPYTHON_XFAILS: dict[str, str] = {
    "test_closures": "nested 3-level closures (outer(1)(2)(3)) cause segfault",
    "test_generators": "*args in generator function (def chain(*iterables)) not supported",
}


@pytest.mark.parametrize(
    "test_name",
    sorted(CPYTHON_ADAPTED_TESTS.keys()),
    ids=sorted(CPYTHON_ADAPTED_TESTS.keys()),
)
def test_cpython_tests(test_name: str):
    """Run an adapted CPython test and diff output against CPython."""
    if test_name in _CPYTHON_XFAILS:
        pytest.xfail(_CPYTHON_XFAILS[test_name])
    source = CPYTHON_ADAPTED_TESTS[test_name]
    result = _diff_test_source(source, timeout=30.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())


# ===========================================================================
# TIER 6b: Django Template Patterns
#
# Tests Django-like template rendering patterns (string interpolation,
# variable lookup, filters, loops) without requiring Django installed.
# ===========================================================================

DJANGO_PATTERN_TESTS = {

    "template_variable": textwrap.dedent("""\
        class Template:
            def __init__(self, text):
                self.text = text
            def render(self, context):
                result = self.text
                for key in context:
                    result = result.replace("{{ " + key + " }}", str(context[key]))
                return result

        t = Template("Hello, {{ name }}! You are {{ age }} years old.")
        print(t.render({"name": "Alice", "age": 30}))
        print(t.render({"name": "Bob", "age": 25}))
    """),

    "template_loop": textwrap.dedent("""\
        # Simple template engine with for-loop support
        def render_list(items, template):
            result = []
            for item in items:
                line = template
                for key in item:
                    line = line.replace("{{ " + key + " }}", str(item[key]))
                result.append(line)
            return result

        items = [
            {"name": "Apple", "price": 1.20},
            {"name": "Banana", "price": 0.50},
            {"name": "Cherry", "price": 3.00},
        ]
        for line in render_list(items, "{{ name }}: ${{ price }}"):
            print(line)
    """),

    "template_filter": textwrap.dedent("""\
        # Template filters (Django-style pipe syntax simulation)
        filters = {
            "upper": lambda s: s.upper(),
            "lower": lambda s: s.lower(),
            "title": lambda s: s.title(),
            "length": lambda s: str(len(s)),
        }

        def apply_filter(value, filter_name):
            if filter_name in filters:
                return filters[filter_name](value)
            return value

        print(apply_filter("hello world", "upper"))
        print(apply_filter("HELLO WORLD", "lower"))
        print(apply_filter("hello world", "title"))
        print(apply_filter("hello", "length"))
    """),

    "template_inheritance": textwrap.dedent("""\
        # Template inheritance pattern
        class BaseTemplate:
            def render_header(self):
                return "=== Header ==="
            def render_content(self):
                return "Default content"
            def render_footer(self):
                return "=== Footer ==="
            def render(self):
                parts = [
                    self.render_header(),
                    self.render_content(),
                    self.render_footer(),
                ]
                return "\\n".join(parts)

        class PageTemplate(BaseTemplate):
            def __init__(self, title, body):
                self.title = title
                self.body = body
            def render_header(self):
                return "=== " + self.title + " ==="
            def render_content(self):
                return self.body

        base = BaseTemplate()
        print(base.render())
        print()
        page = PageTemplate("My Page", "This is the content.")
        print(page.render())
    """),
}


# Known xfail reasons for Django pattern tests
_DJANGO_XFAILS: dict[str, str] = {
    "template_filter": "lambda functions stored in dict not supported",
    "template_loop": "dict with mixed str/float values + str(float) interaction",
}


@pytest.mark.parametrize(
    "test_name",
    sorted(DJANGO_PATTERN_TESTS.keys()),
    ids=sorted(DJANGO_PATTERN_TESTS.keys()),
)
def test_django_patterns(test_name: str):
    """Compile Django-like template patterns and diff against CPython."""
    if test_name in _DJANGO_XFAILS:
        pytest.xfail(_DJANGO_XFAILS[test_name])
    source = DJANGO_PATTERN_TESTS[test_name]
    result = _diff_test_source(source, timeout=30.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())


# ===========================================================================
# TIER 7: Self-Compilation Tests
#
# Tests that compile parts of the fastpy compiler itself with fastpy.
# The ultimate integration test: if the compiler can compile itself (or
# significant subsets), it demonstrates real-world robustness.
# ===========================================================================

class TestSelfCompilation:
    """Compile subsets of the fastpy compiler with fastpy.

    These are aspirational tests — they exercise patterns at the edge
    of what the compiler currently supports. xfail markers track which
    features block each test.
    """

    def test_self_compile_pipeline(self):
        """Compile the pipeline module (simple, few dependencies)."""
        pipeline_path = _PROJECT_ROOT / "compiler" / "pipeline.py"
        if not pipeline_path.exists():
            pytest.skip("pipeline.py not found")

        # We can't compile the full pipeline (it imports codegen which is huge),
        # but we CAN compile and run a program that uses the same patterns:
        # dataclasses, Path operations, try/except, type annotations.
        source = textwrap.dedent("""\
            class CompileError:
                def __init__(self, message, line=None, col=None):
                    self.message = message
                    self.line = line
                    self.col = col
                def __str__(self):
                    loc = ""
                    if self.line is not None:
                        loc = " (line " + str(self.line)
                        if self.col is not None:
                            loc = loc + ", col " + str(self.col)
                        loc = loc + ")"
                    return self.message + loc

            class CompileResult:
                def __init__(self, success, executable=None, errors=None):
                    self.success = success
                    self.executable = executable
                    self.errors = errors if errors is not None else []
                def __str__(self):
                    if self.success:
                        return "Compiled successfully: " + str(self.executable)
                    lines = ["Compilation failed:"]
                    for e in self.errors:
                        lines.append("  " + str(e))
                    return "\\n".join(lines)

            # Test
            e = CompileError("Not implemented: async", line=5, col=10)
            print(e)
            r1 = CompileResult(True, executable="/tmp/out.exe")
            print(r1)
            r2 = CompileResult(False, errors=[
                CompileError("Syntax error", line=1),
                CompileError("Unknown feature"),
            ])
            print(r2)
        """)
        result = _diff_test_source(source, timeout=30.0)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())

    def test_self_compile_ast_visitor(self):
        """Compile an AST visitor pattern (core compiler pattern)."""
        source = textwrap.dedent("""\
            # AST-like node classes (simplified compiler pattern)
            class Node:
                pass

            class BinOp(Node):
                def __init__(self, op, left, right):
                    self.op = op
                    self.left = left
                    self.right = right

            class Num(Node):
                def __init__(self, value):
                    self.value = value

            class Name(Node):
                def __init__(self, id):
                    self.id = id

            # Visitor pattern (like codegen)
            class Evaluator:
                def __init__(self):
                    self.env = {"x": 10, "y": 20}

                def visit(self, node):
                    if isinstance(node, Num):
                        return node.value
                    elif isinstance(node, Name):
                        return self.env[node.id]
                    elif isinstance(node, BinOp):
                        left = self.visit(node.left)
                        right = self.visit(node.right)
                        if node.op == "+":
                            return left + right
                        elif node.op == "-":
                            return left - right
                        elif node.op == "*":
                            return left * right
                        elif node.op == "/":
                            return left // right
                    return 0

            # Build AST: (x + y) * 3 - 5
            tree = BinOp("-",
                BinOp("*",
                    BinOp("+", Name("x"), Name("y")),
                    Num(3)),
                Num(5))

            ev = Evaluator()
            print(ev.visit(tree))
            print(ev.visit(BinOp("+", Num(100), Num(200))))
            print(ev.visit(Name("x")))
        """)
        result = _diff_test_source(source, timeout=30.0)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())

    def test_self_compile_type_system(self):
        """Compile a type system with enum-like dispatching (codegen core)."""
        source = textwrap.dedent("""\
            # Simplified type system (like codegen's VKind/ValueType)
            class VKind:
                INT = 0
                FLOAT = 1
                STR = 2
                BOOL = 3
                LIST = 4
                DICT = 5
                OBJ = 6
                NONE = 7

            class TypedValue:
                def __init__(self, kind, value):
                    self.kind = kind
                    self.value = value

                def is_numeric(self):
                    return self.kind == VKind.INT or self.kind == VKind.FLOAT

                def is_ptr(self):
                    return self.kind in (VKind.STR, VKind.LIST, VKind.DICT, VKind.OBJ)

                def coerce_to(self, target_kind):
                    if self.kind == target_kind:
                        return self
                    if self.kind == VKind.INT and target_kind == VKind.FLOAT:
                        return TypedValue(VKind.FLOAT, float(self.value))
                    if self.kind == VKind.FLOAT and target_kind == VKind.INT:
                        return TypedValue(VKind.INT, int(self.value))
                    return self

            # Type inference simulation
            def infer_binop(left, right, op):
                if left.kind == VKind.FLOAT or right.kind == VKind.FLOAT:
                    l = left.coerce_to(VKind.FLOAT)
                    r = right.coerce_to(VKind.FLOAT)
                    if op == "+":
                        return TypedValue(VKind.FLOAT, l.value + r.value)
                    elif op == "*":
                        return TypedValue(VKind.FLOAT, l.value * r.value)
                else:
                    if op == "+":
                        return TypedValue(VKind.INT, left.value + right.value)
                    elif op == "*":
                        return TypedValue(VKind.INT, left.value * right.value)
                return TypedValue(VKind.NONE, 0)

            # Tests
            a = TypedValue(VKind.INT, 5)
            b = TypedValue(VKind.FLOAT, 2.5)
            c = TypedValue(VKind.INT, 3)

            print(a.is_numeric(), a.is_ptr())
            print(b.is_numeric(), b.is_ptr())

            r1 = infer_binop(a, c, "+")
            print(r1.kind, r1.value)

            r2 = infer_binop(a, b, "*")
            print(r2.kind, r2.value)

            s = TypedValue(VKind.STR, "hello")
            print(s.is_numeric(), s.is_ptr())
        """)
        result = _diff_test_source(source, timeout=30.0)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())

    def test_self_compile_symbol_table(self):
        """Compile a symbol table implementation (compiler infrastructure)."""
        source = textwrap.dedent("""\
            # Symbol table with scoping (like compiler's variable tracking)
            class Scope:
                def __init__(self, parent=None):
                    self.parent = parent
                    self.symbols = {}

                def define(self, name, value):
                    self.symbols[name] = value

                def lookup(self, name):
                    if name in self.symbols:
                        return self.symbols[name]
                    if self.parent is not None:
                        return self.parent.lookup(name)
                    return None

                def child(self):
                    return Scope(parent=self)

            # Build a scope chain
            global_scope = Scope()
            global_scope.define("print", "builtin")
            global_scope.define("len", "builtin")
            global_scope.define("x", "int")

            func_scope = global_scope.child()
            func_scope.define("y", "float")
            func_scope.define("local_var", "str")

            inner_scope = func_scope.child()
            inner_scope.define("z", "bool")

            # Lookups
            print(inner_scope.lookup("z"))      # local
            print(inner_scope.lookup("y"))      # parent
            print(inner_scope.lookup("x"))      # grandparent
            print(inner_scope.lookup("print"))  # global
            print(inner_scope.lookup("missing"))  # not found

            # Shadowing
            func_scope.define("x", "shadowed_float")
            print(inner_scope.lookup("x"))  # should find shadowed version
        """)
        result = _diff_test_source(source, timeout=30.0)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())

    def test_self_compile_ir_builder_pattern(self):
        """Compile an IR builder pattern (codegen's core abstraction)."""
        source = textwrap.dedent("""\
            # Simplified IR builder (like codegen's LLVM IR generation)
            class Instruction:
                def __init__(self, opcode, operands, result=None):
                    self.opcode = opcode
                    self.operands = operands
                    self.result = result

                def __str__(self):
                    ops = ", ".join(str(o) for o in self.operands)
                    if self.result:
                        return self.result + " = " + self.opcode + " " + ops
                    return self.opcode + " " + ops

            class BasicBlock:
                def __init__(self, name):
                    self.name = name
                    self.instructions = []
                    self.terminated = False

                def add(self, instr):
                    if not self.terminated:
                        self.instructions.append(instr)
                    if instr.opcode in ("ret", "br", "cbr"):
                        self.terminated = True

                def __str__(self):
                    lines = [self.name + ":"]
                    for i in self.instructions:
                        lines.append("  " + str(i))
                    return "\\n".join(lines)

            class IRBuilder:
                def __init__(self):
                    self.blocks = []
                    self.current = None
                    self._counter = 0

                def new_block(self, name):
                    bb = BasicBlock(name)
                    self.blocks.append(bb)
                    self.current = bb
                    return bb

                def _tmp(self):
                    self._counter = self._counter + 1
                    return "%" + str(self._counter)

                def add(self, a, b):
                    r = self._tmp()
                    self.current.add(Instruction("add", [a, b], r))
                    return r

                def mul(self, a, b):
                    r = self._tmp()
                    self.current.add(Instruction("mul", [a, b], r))
                    return r

                def ret(self, val):
                    self.current.add(Instruction("ret", [val]))

                def dump(self):
                    for bb in self.blocks:
                        print(bb)

            # Build: return (a + b) * c
            builder = IRBuilder()
            entry = builder.new_block("entry")
            t1 = builder.add("a", "b")
            t2 = builder.mul(t1, "c")
            builder.ret(t2)
            builder.dump()
        """)
        result = _diff_test_source(source, timeout=30.0)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())

    def test_self_compile_codegen_subset(self):
        """Compile a realistic codegen subset: class hierarchy + dispatch."""
        source = textwrap.dedent("""\
            # Realistic compiler pattern: code generation with class dispatch
            class CodeGen:
                def __init__(self):
                    self.output = []
                    self.indent = 0
                    self.variables = {}
                    self._label_count = 0

                def emit(self, line):
                    self.output.append("  " * self.indent + line)

                def new_label(self):
                    self._label_count = self._label_count + 1
                    return "L" + str(self._label_count)

                def generate(self, node):
                    kind = node[0]
                    if kind == "assign":
                        self._gen_assign(node)
                    elif kind == "print":
                        self._gen_print(node)
                    elif kind == "if":
                        self._gen_if(node)
                    elif kind == "while":
                        self._gen_while(node)
                    elif kind == "block":
                        for stmt in node[1]:
                            self.generate(stmt)

                def _gen_assign(self, node):
                    name = node[1]
                    value = self._gen_expr(node[2])
                    self.variables[name] = value
                    self.emit(name + " = " + value)

                def _gen_print(self, node):
                    value = self._gen_expr(node[1])
                    self.emit("print(" + value + ")")

                def _gen_expr(self, expr):
                    if isinstance(expr, int):
                        return str(expr)
                    if isinstance(expr, str):
                        if expr in self.variables:
                            return expr
                        return '"' + expr + '"'
                    if isinstance(expr, tuple):
                        if expr[0] == "+":
                            return self._gen_expr(expr[1]) + " + " + self._gen_expr(expr[2])
                        if expr[0] == "<":
                            return self._gen_expr(expr[1]) + " < " + self._gen_expr(expr[2])
                    return "?"

                def _gen_if(self, node):
                    cond = self._gen_expr(node[1])
                    lbl_else = self.new_label()
                    self.emit("if not " + cond + " goto " + lbl_else)
                    self.indent = self.indent + 1
                    self.generate(node[2])
                    self.indent = self.indent - 1
                    self.emit(lbl_else + ":")

                def _gen_while(self, node):
                    lbl_top = self.new_label()
                    lbl_end = self.new_label()
                    self.emit(lbl_top + ":")
                    cond = self._gen_expr(node[1])
                    self.emit("if not " + cond + " goto " + lbl_end)
                    self.indent = self.indent + 1
                    self.generate(node[2])
                    self.indent = self.indent - 1
                    self.emit("goto " + lbl_top)
                    self.emit(lbl_end + ":")

            # Generate code for a simple program:
            # x = 0
            # while x < 5:
            #     print(x)
            #     x = x + 1
            program = ("block", [
                ("assign", "x", 0),
                ("while", ("<", "x", 5), ("block", [
                    ("print", "x"),
                    ("assign", "x", ("+", "x", 1)),
                ])),
            ])

            cg = CodeGen()
            cg.generate(program)
            for line in cg.output:
                print(line)
        """)
        result = _diff_test_source(source, timeout=30.0)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())


# ===========================================================================
# TIER 7b: Compile Actual Compiler Modules (integration)
#
# Attempt to compile real compiler source files. These are expected to be
# mostly SKIPs until the compiler supports more Python features, but they
# track progress toward full self-hosting.
# ===========================================================================

_COMPILER_FILES = [
    _PROJECT_ROOT / "compiler" / "pipeline.py",
]


@pytest.mark.parametrize(
    "compiler_file",
    [f for f in _COMPILER_FILES if f.exists()],
    ids=[f.stem for f in _COMPILER_FILES if f.exists()],
)
def test_self_compile_real_module(compiler_file: Path):
    """Attempt to compile a real compiler module (progress tracker).

    These tests track self-hosting progress. A SKIP means the compiler
    doesn't support enough features yet. A PASS means it compiled and
    (if it has deterministic output) matches CPython. A FAIL is a bug.
    """
    result = compile_file(compiler_file)
    if not result.success:
        # Expected — track what's blocking
        blockers = [str(e) for e in result.errors[:3]]
        pytest.skip(f"Can't compile yet: {'; '.join(blockers)}")

    # If compilation succeeds, try running it (it won't do much without
    # arguments, but should at least not crash)
    assert result.executable is not None
    run_result = run_executable(result.executable, timeout=10.0)
    if run_result.exit_code != 0 and not run_result.timed_out:
        # Compiled but crashes — that's a failure
        pytest.fail(
            f"Compiled but crashed with exit code {run_result.exit_code}\n"
            f"stderr: {run_result.stderr[:500]}"
        )
