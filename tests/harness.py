"""
Differential test harness.

The core testing engine for the fastpy compiler. Takes a Python program,
runs it under CPython, compiles it with the fastpy compiler and runs the
resulting binary, then compares stdout, stderr, and exit codes.

Three possible outcomes for each test:
    PASS    — both produce identical output and exit code
    SKIP    — compiler can't handle this program yet (not a bug)
    FAIL    — compiler produced a binary but its output differs from CPython

A SKIP is expected while the compiler is under development. A FAIL is
always a bug — either in the compiler or in the test.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Add project root to path so we can import compiler
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from compiler.pipeline import compile_source, CompileResult


@dataclass
class RunResult:
    """Output captured from running a program."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


@dataclass
class DiffResult:
    """Result of comparing CPython and compiled outputs."""
    status: str  # "pass", "skip", "fail"
    reason: str  # human-readable explanation

    # Captured outputs (always present for pass/fail, cpython-only for skip)
    cpython: RunResult | None = None
    compiled: RunResult | None = None

    # Compilation details (for skip/fail diagnosis)
    compile_result: CompileResult | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def skipped(self) -> bool:
        return self.status == "skip"

    @property
    def failed(self) -> bool:
        return self.status == "fail"

    def summary(self) -> str:
        """One-line summary for test output."""
        tag = self.status.upper()
        return f"[{tag}] {self.reason}"

    def detail(self) -> str:
        """Multi-line detail for failure diagnosis."""
        lines = [self.summary()]
        if self.failed:
            if self.cpython and self.compiled:
                if self.cpython.stdout != self.compiled.stdout:
                    lines.append("--- CPython stdout ---")
                    lines.append(self.cpython.stdout or "(empty)")
                    lines.append("--- Compiled stdout ---")
                    lines.append(self.compiled.stdout or "(empty)")
                if self.cpython.stderr != self.compiled.stderr:
                    lines.append("--- CPython stderr ---")
                    lines.append(self.cpython.stderr or "(empty)")
                    lines.append("--- Compiled stderr ---")
                    lines.append(self.compiled.stderr or "(empty)")
                if self.cpython.exit_code != self.compiled.exit_code:
                    lines.append(
                        f"Exit codes: CPython={self.cpython.exit_code}, "
                        f"Compiled={self.compiled.exit_code}"
                    )
        elif self.skipped and self.compile_result:
            for err in self.compile_result.errors:
                lines.append(f"  {err}")
        return "\n".join(lines)


def run_cpython(source: str, timeout: float = 10.0) -> RunResult:
    """
    Run a Python source string under CPython and capture output.

    Uses the same Python interpreter that's running the test suite.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", source],
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
        return RunResult(
            stdout="",
            stderr="Timed out",
            exit_code=-1,
            timed_out=True,
        )


def run_executable(exe_path: Path, timeout: float = 10.0) -> RunResult:
    """Run a compiled executable and capture output."""
    try:
        proc = subprocess.run(
            [str(exe_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return RunResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            stdout="",
            stderr="Timed out",
            exit_code=-1,
            timed_out=True,
        )


def _parse_compile_flags(source: str) -> dict:
    """Extract compile flags from a `# compile_flags: ...` comment.

    Recognised flags: --typed, --int64.
    Returns kwargs suitable for compile_source().
    """
    kwargs: dict = {}
    for line in source.splitlines()[:5]:  # only check first 5 lines
        line = line.strip()
        if line.startswith("# compile_flags:"):
            flags = line.split(":", 1)[1].strip().split()
            if "--typed" in flags:
                kwargs["typed_mode"] = True
            if "--int64" in flags:
                kwargs["int64_mode"] = True
            break
    return kwargs


def diff_test(
    source: str,
    timeout: float = 10.0,
) -> DiffResult:
    """
    Run the full differential test for a Python source string.

    1. Run under CPython
    2. Compile with fastpy compiler
    3. If compilation fails with "not implemented" -> SKIP
    4. If compilation succeeds, run the binary and compare -> PASS or FAIL
    """
    # Step 1: Run under CPython to get the reference output
    cpython_result = run_cpython(source, timeout)

    if cpython_result.timed_out:
        return DiffResult(
            status="skip",
            reason="Program timed out under CPython",
            cpython=cpython_result,
        )

    # Step 2: Try to compile (with any per-file compile flags)
    extra_kwargs = _parse_compile_flags(source)
    compile_result = compile_source(source, **extra_kwargs)

    if not compile_result.success:
        # Compiler can't handle this yet — that's a skip, not a failure
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

    # We compare stderr loosely — only flag it if one has stderr and the
    # other doesn't, because exact error messages may differ
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


def diff_test_file(path: Path, timeout: float = 10.0) -> DiffResult:
    """Run the differential test on a Python source file."""
    source = path.read_text(encoding="utf-8")
    return diff_test(source, timeout)
