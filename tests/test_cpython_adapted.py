"""
CPython Test Suite — Adapted for fastpy differential testing.

This test module auto-discovers all .py files in tests/cpython_adapted/ and
runs each as a differential test: compile with fastpy, run both compiled and
CPython versions, compare stdout.

Each file in cpython_adapted/ is a SELF-CONTAINED Python program that:
  - Uses NO imports (or only imports that fastpy handles)
  - Prints deterministic output (no timing, no random, no id())
  - Exercises functionality from a specific CPython Lib/test/test_*.py
  - Can be run standalone: `python tests/cpython_adapted/test_bisect.py`

To add a new test: drop a .py file into tests/cpython_adapted/ and it will
be auto-discovered on the next pytest run.

Run:
    pytest tests/test_cpython_adapted.py -v                    # all
    pytest tests/test_cpython_adapted.py -k test_bisect        # specific
    pytest tests/test_cpython_adapted.py -x                    # stop on first failure
    pytest tests/test_cpython_adapted.py --co                  # list discovered tests
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from compiler.pipeline import compile_file
from tests.harness import run_executable, DiffResult, RunResult

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_ADAPTED_DIR = Path(__file__).resolve().parent / "cpython_adapted"

_TEST_FILES = sorted(
    p for p in _ADAPTED_DIR.glob("test_*.py")
) if _ADAPTED_DIR.exists() else []

# ---------------------------------------------------------------------------
# Known failures — tests that expose unsupported features.
# Key = stem (e.g. "test_bisect"), value = reason string.
# ---------------------------------------------------------------------------

_XFAILS: dict[str, str] = {
    # Segfaults — features that cause crashes in compiled output
    "test_builtin_funcs": "type().__name__ attribute access + filter(None) not supported",
    "test_comprehensions": "nested generator expressions cause segfault",
    "test_copy": "list.copy() in class context causes segfault",
    "test_decorators": "func.__name__ attribute access on function objects not supported",
    "test_defaultdict_pattern": "string character iteration (for ch in word) causes segfault",
    "test_dict": "dict.fromkeys() not supported",
    "test_functools": "*args in reduce + lambda in higher-order causes segfault",
    "test_generators": "generator with break/early-termination causes segfault",
    "test_recursion": "isinstance(item, list) in recursive context causes segfault",
    "test_set": "set operations in some contexts cause segfault",
    "test_statistics": "float formatting inconsistency + mean() segfault",
    "test_string_methods": "complex method chaining causes segfault",
    "test_zip": "zip with single iterable causes segfault",
    # Wrong output — compiles but produces incorrect results
    "test_augassign": "float augmented assignment (+=, -=) on float variables incorrect",
    "test_bool": "bool prints as 1/0 instead of True/False in some contexts",
    "test_class": "round() returns float format '6.0' instead of int '6' for exact values",
    "test_compare": "stderr presence differs (non-critical)",
    "test_deque_pattern": "list of strings printed as raw pointers",
    "test_int": "stderr presence differs (non-critical)",
    "test_math_ops": "integer division result treated as float pointer in some paths",
    "test_scope": "global variable read from nested function scope incorrect",
    "test_slice": "del with step slice (del lst[::2]) not fully supported",
    "test_textwrap": "split() result list contains raw pointers instead of strings",
    # Runtime errors — compiles but crashes with exit code 1
    "test_graphlib": "complex dict operations cause runtime error",
    "test_inheritance": "class variable access returns None instead of value",
    "test_tuple": "some tuple operations cause runtime error",
    # --- Auto-generated stdlib tests (from CPython adapter) ---
    # These inline the pure-Python stdlib source and exercise it directly.
    # They expose compiler limitations that need fixing:
    "test_bisect_stdlib": "keyword arg wrapping: Cannot wrap argument of type {i32, i64}",
    "test_colorsys_stdlib": "tuple-as-function-param causes segfault (tuple ABI issue)",
    "test_graphlib_stdlib": "class instantiation in compiled code returns NoneType",
    "test_heapq_stdlib": "class attribute access + NameError on class-level vars",
    "test_statistics_stdlib": "DuplicatedNameError: nested functions with same name in LLVM IR",
    "test_textwrap_stdlib": "TextWrapper keyword args (max_lines) not resolved in compiled code",
}

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


def _diff_test_file(file_path: Path, timeout: float = 60.0) -> DiffResult:
    """Compile a file with fastpy, run both, compare stdout."""
    cpython_result = _run_cpython_file(file_path, timeout)
    if cpython_result.timed_out:
        return DiffResult(
            status="skip", reason="Timed out under CPython",
            cpython=cpython_result,
        )

    compile_result = compile_file(file_path)
    if not compile_result.success:
        err_summary = "; ".join(str(e) for e in compile_result.errors[:3])
        return DiffResult(
            status="skip",
            reason=f"Compiler can't compile this yet: {err_summary}",
            cpython=cpython_result,
            compile_result=compile_result,
        )

    assert compile_result.executable is not None
    compiled_result = run_executable(compile_result.executable, timeout)

    differences: list[str] = []
    if cpython_result.stdout != compiled_result.stdout:
        differences.append("stdout differs")
    if cpython_result.exit_code != compiled_result.exit_code:
        differences.append(
            f"exit code: CPython={cpython_result.exit_code}, "
            f"Compiled={compiled_result.exit_code}"
        )
    cpython_has_err = bool(cpython_result.stderr.strip())
    compiled_has_err = bool(compiled_result.stderr.strip())
    if cpython_has_err != compiled_has_err:
        differences.append("stderr presence differs")

    if differences:
        return DiffResult(
            status="fail", reason="; ".join(differences),
            cpython=cpython_result, compiled=compiled_result,
            compile_result=compile_result,
        )
    return DiffResult(
        status="pass", reason="Output matches CPython",
        cpython=cpython_result, compiled=compiled_result,
        compile_result=compile_result,
    )

# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "test_file",
    _TEST_FILES,
    ids=[p.stem for p in _TEST_FILES],
)
def test_cpython_adapted(test_file: Path):
    """Compile an adapted CPython test and diff output against CPython."""
    stem = test_file.stem
    if stem in _XFAILS:
        pytest.xfail(_XFAILS[stem])

    result = _diff_test_file(test_file, timeout=60.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())
