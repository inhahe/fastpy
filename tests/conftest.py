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

from tests.harness import diff_test, diff_test_file, DiffResult


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
    def _assert(source: str, timeout: float = 10.0) -> DiffResult:
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
    def _assert(path: Path, timeout: float = 10.0) -> DiffResult:
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
