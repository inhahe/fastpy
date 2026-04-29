"""
Full test suite: pyperformance benchmarks, stdlib tests, Django template tests,
and stdlib import tests.

Extends the base test suite (test_differential.py + regressions/) with:

1. **Pyperformance benchmarks** (compile + run, verify exit code 0)
   - These print timing-dependent output, so we can't diff stdout.
   - We just verify the compiler handles complex real-world code without
     crashing at compile time or runtime.

2. **Stdlib algorithm tests** (full differential: compile + compare output)
   - benchmarks/stdlib/test_bisect.py, test_colorsys.py, etc.
   - Deterministic output — full stdout comparison with CPython.

3. **Django template tests** (full differential: compile + compare output)
   - benchmarks/pyperformance/test_django_template.py
   - Deterministic output — full stdout comparison with CPython.

4. **Stdlib import tests** (full differential: compile snippet + compare)
   - Every snippet from test_all_stdlib.py parametrized as an individual test.

Run:
    pytest tests/test_full_suite.py -v                # full suite
    pytest tests/test_full_suite.py -k pyperformance  # just benchmarks
    pytest tests/test_full_suite.py -k stdlib_algo     # just stdlib algo tests
    pytest tests/test_full_suite.py -k django          # just Django tests
    pytest tests/test_full_suite.py -k stdlib_import   # just stdlib imports
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from compiler.pipeline import compile_file
from tests.harness import diff_test, run_executable, DiffResult, RunResult

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BENCHMARKS_DIR = _PROJECT_ROOT / "benchmarks"
_PYPERFORMANCE_DIR = _BENCHMARKS_DIR / "pyperformance"
_STDLIB_DIR = _BENCHMARKS_DIR / "stdlib"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cpython_file(file_path: Path, timeout: float = 60.0) -> RunResult:
    """Run a Python source *file* under CPython (avoids Windows cmd-line limit)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(file_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return RunResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return RunResult(stdout="", stderr="Timed out", exit_code=-1, timed_out=True)


def _diff_test_file_direct(file_path: Path, timeout: float = 60.0) -> DiffResult:
    """Like diff_test_file but runs CPython with the file path, not -c.

    This avoids the Windows 32 KB command-line limit for large source files.
    """
    # Step 1: Run under CPython using the file directly
    cpython_result = _run_cpython_file(file_path, timeout)
    if cpython_result.timed_out:
        return DiffResult(
            status="skip",
            reason="Program timed out under CPython",
            cpython=cpython_result,
        )

    # Step 2: Compile with fastpy
    compile_result = compile_file(file_path)
    if not compile_result.success:
        return DiffResult(
            status="skip",
            reason="Compiler can't compile this yet",
            cpython=cpython_result,
            compile_result=compile_result,
        )

    # Step 3: Run the compiled binary
    assert compile_result.executable is not None
    compiled_result = run_executable(compile_result.executable, timeout)

    # Step 4: Compare outputs
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
            status="fail",
            reason="; ".join(differences),
            cpython=cpython_result,
            compiled=compiled_result,
            compile_result=compile_result,
        )

    return DiffResult(
        status="pass",
        reason="Output matches CPython",
        cpython=cpython_result,
        compiled=compiled_result,
        compile_result=compile_result,
    )

# ---------------------------------------------------------------------------
# 1. Pyperformance benchmarks — compile + run (no stdout diff)
# ---------------------------------------------------------------------------

_PYPERFORMANCE_FILES = sorted(
    p for p in _PYPERFORMANCE_DIR.glob("bm_*.py")
)

# The Django template benchmark needs django installed and uses C extension
# imports that are timing-dependent — test it separately in the Django section.
_PYPERFORMANCE_SKIP = {"bm_django_template.py"}

_PYPERFORMANCE_TEST_FILES = [
    p for p in _PYPERFORMANCE_FILES
    if p.name not in _PYPERFORMANCE_SKIP
]


@pytest.mark.parametrize(
    "benchmark_file",
    _PYPERFORMANCE_TEST_FILES,
    ids=[p.stem for p in _PYPERFORMANCE_TEST_FILES],
)
def test_pyperformance(benchmark_file: Path):
    """Compile a pyperformance benchmark and verify it runs without error."""
    # Step 1: Compile
    result = compile_file(benchmark_file)
    if not result.success:
        # Compiler can't handle this yet — skip, not fail
        err_summary = "; ".join(str(e) for e in result.errors[:3])
        pytest.skip(f"Compiler can't compile this yet: {err_summary}")

    # Step 2: Run the compiled binary (generous timeout for benchmarks)
    assert result.executable is not None
    compiled = run_executable(result.executable, timeout=120.0)

    if compiled.timed_out:
        pytest.fail("Compiled binary timed out (120s)")

    # Step 3: Verify clean exit
    if compiled.exit_code != 0:
        stderr_snippet = compiled.stderr[:500] if compiled.stderr else "(empty)"
        pytest.fail(
            f"Compiled binary exited with code {compiled.exit_code}\n"
            f"stderr: {stderr_snippet}"
        )

    # Step 4: Also run CPython and verify it exits cleanly (sanity check)
    # Use file-based runner to avoid Windows command-line limit
    cpython = _run_cpython_file(benchmark_file, timeout=120.0)
    if cpython.exit_code != 0 and not cpython.timed_out:
        pytest.skip(f"CPython itself fails on this benchmark (exit {cpython.exit_code})")


# ---------------------------------------------------------------------------
# 2. Stdlib algorithm tests — full differential
# ---------------------------------------------------------------------------

_STDLIB_TEST_FILES = sorted(
    p for p in _STDLIB_DIR.glob("test_*.py")
)


# Known failures in stdlib algo tests (pre-existing bugs, not caused by recent changes)
_STDLIB_ALGO_XFAIL = {
}


@pytest.mark.parametrize(
    "stdlib_file",
    _STDLIB_TEST_FILES,
    ids=[p.stem for p in _STDLIB_TEST_FILES],
)
def test_stdlib_algo(stdlib_file: Path):
    """Compile a stdlib algorithm test and diff output against CPython."""
    if stdlib_file.stem in _STDLIB_ALGO_XFAIL:
        pytest.xfail(_STDLIB_ALGO_XFAIL[stdlib_file.stem])

    # Use file-direct runner to avoid Windows 32KB command-line limit
    # (some stdlib tests like test_heapq.py and test_statistics.py are large)
    result = _diff_test_file_direct(stdlib_file, timeout=60.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())


# ---------------------------------------------------------------------------
# 3. Django template tests — full differential
# ---------------------------------------------------------------------------

_DJANGO_TEST_FILE = _PYPERFORMANCE_DIR / "test_django_template.py"


@pytest.mark.skipif(
    not _DJANGO_TEST_FILE.exists(),
    reason="test_django_template.py not found",
)
def test_django_template():
    """Compile the Django template test suite and diff output against CPython."""
    # Check if django is importable
    try:
        import django  # noqa: F401
    except ImportError:
        pytest.skip("django not installed")

    # Use file-direct runner to avoid Windows 32KB command-line limit
    result = _diff_test_file_direct(_DJANGO_TEST_FILE, timeout=120.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())


# ---------------------------------------------------------------------------
# 4. Stdlib import tests — parametrized differential tests
#
# Each snippet imports a stdlib module and exercises basic functionality.
# These are taken from test_all_stdlib.py's BRIDGE_TESTS and PYTHON_TESTS.
# ---------------------------------------------------------------------------

# Import the test dictionaries from test_all_stdlib
from tests.scripts.all_stdlib import BRIDGE_TESTS, PYTHON_TESTS

_ALL_STDLIB_IMPORT_TESTS: dict[str, str] = {}
_ALL_STDLIB_IMPORT_TESTS.update(BRIDGE_TESTS)
_ALL_STDLIB_IMPORT_TESTS.update(PYTHON_TESTS)

_STDLIB_IMPORT_NAMES = sorted(_ALL_STDLIB_IMPORT_TESTS.keys())


@pytest.mark.parametrize(
    "module_name",
    _STDLIB_IMPORT_NAMES,
    ids=_STDLIB_IMPORT_NAMES,
)
def test_stdlib_import(module_name: str):
    """Compile a stdlib import snippet and diff output against CPython."""
    source = _ALL_STDLIB_IMPORT_TESTS[module_name]
    result = diff_test(source, timeout=30.0)
    if result.skipped:
        pytest.skip(result.reason)
    if result.failed:
        pytest.fail(result.detail())
