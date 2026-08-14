"""
Performance-invariant tests: which functions get the bare scalar ABI.

The differential harness compares *output*, so it cannot see an ABI
regression -- a function demoted from the bare `i64` ABI to the tagged
FpyValue ABI still prints the right answer, just far more slowly. That is
exactly how `function calls 10M` silently regressed ~9x: `_duf_select_abi`
began (correctly) requiring positive evidence before choosing the bare ABI,
and `_csa_build_var_types` had no arm recording a plain int, so the ordinary
`add(i, 1)` counter loop stopped qualifying.

These assert on generated IR rather than on wall-clock time, so they are
deterministic and unaffected by machine load -- a timing test for this would
be unusable on a busy machine, since the benchmark it guards runs in ~11ms.

`test_declines_*` matter as much as `test_uses_bare_abi_*`: the bare ABI has
nowhere to put a runtime tag, so claiming it without evidence is
BUG-UNTYPED-PARAM-BARE-ABI (a str pointer read back as an integer, `len()`
answering 0). A change that makes the evidence more eager must keep failing
these.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from compiler.pipeline import compile_source  # noqa: E402

_ADD = "def add(a, b):\n    return a + b\n"
_SINK = "def sink(v):\n    return len(v)\n"


def _param_abi(src: str, func: str = "add") -> str:
    """Return 'bare' or 'fv' for `func`'s parameter ABI in the emitted IR."""
    result = compile_source(src)
    assert result.success, f"compile failed: {result.errors}"
    ir = result.ir or ""
    m = re.search(
        r'define internal ([^@]+)@"fastpy\.user\.%s"\(([^)]*)\)' % func, ir)
    assert m is not None, f"{func} not found in IR"
    return "fv" if "{i32, i64}" in m.group(2) else "bare"


class TestBareABIForCounterLoops:
    """The shapes that must stay fast."""

    @pytest.mark.parametrize("body", [
        # while counter
        "t = 0\ni = 0\nwhile i < 10:\n    t = t + add(i, 1)\n    i = i + 1\n",
        # for-range counter
        "t = 0\nfor i in range(10):\n    t = t + add(i, 1)\n",
        # augmented assignment
        "t = 0\ni = 0\nwhile i < 10:\n    t = t + add(i, 1)\n    i += 1\n",
        # nested range loops
        "t = 0\nfor i in range(5):\n    for j in range(5):\n        t = t + add(i, j)\n",
        # int derived through len()
        "L = [1, 2, 3]\nn = len(L)\nt = add(n, 1)\n",
        # int derived through arithmetic on another proven int
        "i = 0\nj = i * 2 + 1\nt = add(j, 1)\n",
        # literal-to-literal tuple unpack
        "i, j = 0, 1\nt = add(i, j)\n",
        # mutual reference: needs the agreement phase, since neither name is
        # provable on its own, and both are grounded by their first binding
        "i = 0\nj = 1\ni, j = j, i\nt = add(i, j)\n",
    ], ids=["while", "for_range", "augassign", "nested_range", "len",
            "derived", "tuple_unpack", "swap"])
    def test_uses_bare_abi(self, body):
        assert _param_abi(_ADD + body) == "bare"


class TestDeclinesWithoutEvidence:
    """The shapes that must stay tagged; each one is a bug if it goes bare."""

    def test_declines_when_rebound_to_str(self):
        src = _ADD + 'i = 1\nt = add(i, 1)\ni = "s"\nprint(i)\n'
        assert _param_abi(src) == "fv"

    def test_declines_for_loop_over_list(self):
        src = _ADD + "L = [1, 2]\nt = 0\nfor i in L:\n    t = t + add(i, 1)\n"
        assert _param_abi(src) == "fv"

    def test_declines_when_range_is_shadowed(self):
        src = (_SINK + 'def range(n):\n    return ["ab", "cde"]\n'
               "for i in range(2):\n    print(sink(i))\n")
        assert _param_abi(src, "sink") == "fv"

    def test_declines_when_len_is_shadowed(self):
        src = ('def len(x):\n    return "zz"\ndef sink(v):\n    return v\n'
               "L = [1, 2, 3]\nn = len(L)\nprint(sink(n))\n")
        assert _param_abi(src, "sink") == "fv"

    def test_declines_when_program_uses_bigint(self):
        # Overflow promotion can put a heap pointer in an int-tagged name.
        src = (_ADD + "big = 2 ** 70\nt = 0\ni = 0\n"
               "while i < 10:\n    t = t + add(i, 1)\n    i = i + 1\n"
               "print(big)\n")
        assert _param_abi(src) == "fv"

    def test_declines_on_starred_unpack(self):
        # A `*b` makes the pairing depend on a length this pass cannot see.
        src = _ADD + "a, *b = 1, 2, 3\nt = add(a, 1)\n"
        assert _param_abi(src) == "fv"

    def test_declines_on_unpack_from_call(self):
        # The right-hand side is not a literal sequence, so which element
        # reaches which name is not visible in the AST.
        src = _ADD + "def f():\n    return (1, 2)\na, b = f()\nt = add(a, b)\n"
        assert _param_abi(src) == "fv"

    def test_declines_when_unpacked_name_is_rebound_to_str(self):
        src = _ADD + 'i, j = 0, 1\nt = add(i, j)\ni = "s"\nprint(i)\n'
        assert _param_abi(src) == "fv"

    def test_declines_on_base_less_cycle(self):
        # `x = y; y = x` never binds an int; nothing may be inferred from it.
        src = _ADD + "x = y\ny = x\nt = add(x, 1)\n"
        assert _param_abi(src) == "fv"
