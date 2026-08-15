"""
Pytest configuration and shared fixtures for the fastpy test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.harness import diff_test, diff_test_file, DiffResult, DEFAULT_TIMEOUT


@pytest.fixture
def assert_compiles():
    """
    Fixture that compiles a Python source string and asserts it matches CPython.

    Usage:
        def test_something(assert_compiles):
            assert_compiles("print(1 + 2)")

    Skips if the compiler can't handle the program yet.
    Fails if the compiled output differs from CPython.
    """
    def _assert(source: str, timeout: float = DEFAULT_TIMEOUT) -> DiffResult:
        result = diff_test(source, timeout)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())
        return result
    return _assert


@pytest.fixture
def assert_file_compiles():
    """
    Fixture that compiles a Python source file and asserts it matches CPython.

    Usage:
        def test_something(assert_file_compiles):
            assert_file_compiles(Path("tests/programs/test_arith.py"))
    """
    def _assert(path: Path, timeout: float = DEFAULT_TIMEOUT) -> DiffResult:
        result = diff_test_file(path, timeout)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())
        return result
    return _assert


# ---------------------------------------------------------------------------
# Auto-collection of regression test files
# ---------------------------------------------------------------------------

_REGRESSIONS_DIR = Path(__file__).parent / "regressions"
_PROGRAMS_DIR = Path(__file__).parent / "programs"


def _collect_python_files(directory: Path) -> list[Path]:
    """Collect all .py files in a directory (non-recursive), excluding __init__."""
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.glob("*.py")
        if p.name != "__init__.py"
    )


def pytest_collect_file(parent, file_path):
    """
    Custom collector: .py files in regressions/ and programs/ are treated
    as test programs to run through the differential harness.
    """
    # Only collect from our specific directories
    try:
        file_path.relative_to(_REGRESSIONS_DIR)
    except ValueError:
        try:
            file_path.relative_to(_PROGRAMS_DIR)
        except ValueError:
            return None

    if file_path.suffix == ".py" and file_path.name != "__init__.py":
        return ProgramTestFile.from_parent(parent, path=file_path)
    return None


class ProgramTestFile(pytest.File):
    """Custom collector that runs a Python file through the differential harness."""

    def collect(self):
        yield ProgramTestItem.from_parent(
            self,
            name=self.path.stem,
        )


class ProgramTestItem(pytest.Item):
    """A single program differential test."""

    def __init__(self, name, parent, **kwargs):
        super().__init__(name, parent, **kwargs)

    def runtest(self):
        result = diff_test_file(self.path)
        if result.skipped:
            pytest.skip(result.reason)
        if result.failed:
            pytest.fail(result.detail())

    def repr_failure(self, excinfo):
        return str(excinfo.value)

    def reportinfo(self):
        return self.path, 0, f"program: {self.path.name}"


# ---------------------------------------------------------------------------
# Coverage warning: a green run that skipped the regression corpus
# ---------------------------------------------------------------------------
#
# `pytest_collect_file` above is a *discovery* hook: it only fires for files
# pytest walks into.  Naming test files explicitly on the command line
# overrides `testpaths`, so the hook never sees `regressions/` and the whole
# corpus — the record of every bug already fixed — is silently absent.  The run
# is green, just several hundred tests smaller, which is the worst possible
# failure mode for something whose entire job is to tell you a change is safe.
#
# pytest cannot be configured out of this (explicit paths always win), so the
# fix is to make it loud rather than to prevent it.  We warn only when the
# corpus is *entirely* absent while other tests ran: naming a handful of
# regression files is obviously deliberate and stays quiet.
# DEBT-NAMED-SUITES-SKIP-THE-REGRESSION-CORPUS.

def pytest_collection_modifyitems(session, config, items):
    config._fastpy_program_items = sum(
        1 for i in items if isinstance(i, ProgramTestItem))
    config._fastpy_other_items = len(items) - config._fastpy_program_items


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    collected = getattr(config, "_fastpy_program_items", None)
    if collected is None or collected > 0:
        return
    if not getattr(config, "_fastpy_other_items", 0):
        return  # collected nothing at all; not this hazard
    available = (len(_collect_python_files(_REGRESSIONS_DIR))
                 + len(_collect_python_files(_PROGRAMS_DIR)))
    if not available:
        return
    terminalreporter.write_sep("=", "partial run", yellow=True, bold=True)
    terminalreporter.write_line(
        f"This run covered 0 of {available} regression/program files. The "
        f"corpus is collected by directory discovery, which naming test "
        f"files on the command line bypasses.")
    terminalreporter.write_line(
        "Before calling a change safe, run: python -m pytest tests")
