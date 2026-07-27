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

One important exception to "a compile failure is a SKIP": an **LLVM verifier**
error is not an unsupported feature, it is invalid IR that codegen should never
have emitted, and no amount of feature work will turn it into a PASS. Those are
classified as FAIL — see `_VERIFIER_ERROR_SIGNS` / `_is_verifier_error`. This
matters: BUG-DECREF-DOES-NOT-DOMINATE sat green in the suite as a SKIP for a
long time precisely because it was indistinguishable from "not implemented yet".
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Add project root to path so we can import compiler
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from compiler.pipeline import compile_source, CompileResult


# Wall-clock budget for one differential test: the CPython reference run and
# the compiled binary each get this long. It bounds a genuine hang (an
# infinite loop in generated code) without being tight enough to fire on a
# busy machine — the slowest legitimate file in the suite runs in ~2 s, so
# this is a 15x margin, and on a green run the headroom costs nothing because
# nothing waits on it. It used to be 10 s, which was enough for a full run
# under load to fail a test that passed standalone seconds later.
# BUG-SUITE-DEFAULT-TIMEOUT-FLAKES-UNDER-LOAD.
DEFAULT_TIMEOUT = 30.0


# Substrings that identify an LLVM *verifier* rejection rather than a fastpy
# "feature not supported" message. Invalid IR is always a codegen bug, so these
# are reported as FAIL instead of being absorbed into the SKIP bucket.
_VERIFIER_ERROR_SIGNS = (
    "does not dominate all uses",
    "Broken module found",
    "Instruction referencing instruction not embedded in a basic block",
    "PHI node entries do not match predecessors",
    "Invalid operand types",
    "Basic Block does not have terminator",
    "Terminator found in the middle of a basic block",
    "Instruction does not dominate",
)


def _is_verifier_error(compile_result: CompileResult) -> bool:
    """True when a failed compile was rejected by the LLVM verifier.

    A verifier error means codegen emitted structurally invalid IR — a
    different category from "this Python feature isn't implemented yet" — so
    the caller must surface it as a failure, never as a skip.
    """
    for err in getattr(compile_result, "errors", None) or ():
        msg = getattr(err, "message", None) or str(err)
        if any(sign in msg for sign in _VERIFIER_ERROR_SIGNS):
            return True
    return False


@dataclass
class RunResult:
    """Output captured from running a program."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    # Wall-clock seconds the process ran for. Reported on a timeout so the
    # next occurrence separates "this hung" from "this was merely slow":
    # a program that normally finishes in 0.1 s and burned the whole budget
    # is an infinite loop, one that took 29.9 s of a 30 s budget is load.
    duration: float = 0.0


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
            # A killed process has no output to diff, so dumping "(empty)"
            # against CPython's stdout would bury the one fact that matters
            # — which the summary line already states.
            if self.compiled is not None and self.compiled.timed_out:
                return "\n".join(lines)
            # A failure with no compiled run is an invalid-IR rejection: the
            # compiler errors are the whole story.
            if self.compiled is None and self.compile_result:
                for err in self.compile_result.errors:
                    lines.append(f"  {err}")
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


def run_cpython(source: str, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    """
    Run a Python source string under CPython and capture output.

    Uses the same Python interpreter that's running the test suite.
    """
    started = time.monotonic()
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
            duration=time.monotonic() - started,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            stdout="",
            stderr="Timed out",
            exit_code=-1,
            timed_out=True,
            duration=time.monotonic() - started,
        )


def run_executable(exe_path: Path, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    """Run a compiled executable and capture output."""
    started = time.monotonic()
    try:
        # Ensure Python DLLs (python3XX.dll) are on PATH for the compiled
        # executable, which links against the CPython bridge.
        env = os.environ.copy()
        python_dir = os.path.dirname(sys.executable)
        env["PATH"] = python_dir + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [str(exe_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        return RunResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            duration=time.monotonic() - started,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            stdout="",
            stderr="Timed out",
            exit_code=-1,
            timed_out=True,
            duration=time.monotonic() - started,
        )


def _runtime_stderr(stderr: str) -> str:
    """Drop CPython's *compile-time* warnings from a stderr capture.

    The reference interpreter emits SyntaxWarning while compiling the source
    — `'return' in a 'finally' block`, an invalid escape sequence, `is` with
    a literal.  Those say something about the source text under one
    particular CPython version, not about what the program does, and fastpy
    is a different compiler with its own diagnostics.  A test that exercises
    a warned-about-but-legal construct would otherwise be permanently
    unrunnable, so the warning and the source line it echoes are removed
    before the presence check.  Anything the program itself writes to stderr
    — including warnings raised at *run* time — is left alone.
    """
    out: list[str] = []
    skip_echo = False
    for line in stderr.splitlines(True):
        if "SyntaxWarning:" in line:
            # `file:line: SyntaxWarning: msg` is followed by the offending
            # source line, indented.
            skip_echo = True
            continue
        if skip_echo:
            skip_echo = False
            if line[:1].isspace():
                continue
        out.append(line)
    return "".join(out)


def _parse_compile_flags(source: str) -> dict:
    """Extract compile flags from a `# compile_flags: ...` comment.

    Recognised flags: --typed, --int64, --threading gil, --threading free, -t.
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
            if "-t" in flags:
                kwargs["threading_mode"] = 2
            elif "--threading" in flags:
                idx = flags.index("--threading")
                if idx + 1 < len(flags):
                    mode = flags[idx + 1]
                    if mode == "gil":
                        kwargs["threading_mode"] = 1
                    elif mode == "free":
                        kwargs["threading_mode"] = 2
            break
    return kwargs


def diff_test(
    source: str,
    timeout: float = DEFAULT_TIMEOUT,
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
        # Invalid IR is a codegen bug, not a missing feature — never a skip.
        if _is_verifier_error(compile_result):
            return DiffResult(
                status="fail",
                reason="Codegen emitted invalid IR (LLVM verifier rejected it)",
                cpython=cpython_result,
                compile_result=compile_result,
            )
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

    # Clean up the temp build directory
    import shutil
    exe_dir = compile_result.executable.parent
    try:
        shutil.rmtree(exe_dir, ignore_errors=True)
    except OSError:
        pass

    # Step 4: Compare outputs.
    #
    # A timed-out binary is reported as a timeout, before the generic diff
    # gets to describe it as "stdout differs; exit code: ..." — which is what
    # a killed process looks like (no output, exit code -1) and is why the
    # last occurrence cost a bisect to identify. CPython finished, so the
    # program itself terminates; either codegen produced a loop that does
    # not, or the machine was too busy to finish it inside the budget.
    # BUG-SUITE-DEFAULT-TIMEOUT-FLAKES-UNDER-LOAD.
    if compiled_result.timed_out:
        return DiffResult(
            status="fail",
            reason=(
                f"compiled program timed out after {timeout:g}s "
                f"(CPython finished the same program in "
                f"{cpython_result.duration:.2f}s)"
            ),
            cpython=cpython_result,
            compiled=compiled_result,
            compile_result=compile_result,
        )

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
    cpython_has_err = bool(_runtime_stderr(cpython_result.stderr).strip())
    compiled_has_err = bool(_runtime_stderr(compiled_result.stderr).strip())
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


def diff_test_file(path: Path, timeout: float = DEFAULT_TIMEOUT) -> DiffResult:
    """Run the differential test on a Python source file."""
    source = path.read_text(encoding="utf-8")
    return diff_test(source, timeout)
