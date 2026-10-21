"""
Interactive REPL for fastpy.

Each input line is compiled to a native executable via the normal fastpy
pipeline and executed as a subprocess.  State persists across lines by
replaying all previous statements into each subsequent compilation unit.

Usage:
    python -m compiler --repl
"""

from __future__ import annotations

import ast
import subprocess
import tempfile
import traceback
from pathlib import Path


# Sentinel for expression result extraction.
_SENTINEL = "__REPL_EXPR::"
# Sentinel printed before new user code to separate replay output.
_OUTPUT_START = "__REPL_OUTPUT_START__"


class ReplSession:
    """Manages persistent state across REPL inputs.

    State model — statement replay:
    Every successfully executed statement is recorded in order. When
    compiling a new REPL line, ALL previous statements are replayed
    as a preamble. This correctly handles class instances, closures,
    and any other state that can't round-trip through repr().

    Function and class definitions are deduplicated (latest wins).
    """

    def __init__(self):
        """Create a REPL session, which compiles in this process."""
        self._line_count = 0

        # Ordered log of all successfully executed statements.
        # Each entry is a source string for one statement.
        self._statement_log: list[str] = []

        # Track latest func/class def positions in the log so we can
        # deduplicate on redefinition.
        self._func_def_idx: dict[str, int] = {}   # name -> index in _statement_log
        self._class_def_idx: dict[str, int] = {}   # name -> index in _statement_log

        # Track which variable names are live (for expression display).
        self._known_vars: set[str] = set()

        # Temporary directory for compiled executables.
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="fastpy_repl_"))

    def eval_line(self, source: str) -> str | None:
        """Compile and execute one REPL input.  Returns display string or None."""
        source = source.strip()
        if not source:
            return None

        self._line_count += 1

        # Parse to classify the input.
        try:
            tree = ast.parse(source, mode='exec')
        except SyntaxError as e:
            return f"SyntaxError: {e.msg} (line {e.lineno})"

        if not tree.body:
            return None

        # Classify: bare expression?
        is_bare_expr = (len(tree.body) == 1
                        and isinstance(tree.body[0], ast.Expr))

        # --- Build the full program ---
        program_parts: list[str] = []

        # 1. Replay all previous statements (their output is suppressed).
        for stmt_src in self._statement_log:
            program_parts.append(stmt_src)

        # 2. Output-start sentinel: only output after this line is shown.
        program_parts.append(f'print("{_OUTPUT_START}")')

        # 3. Emit the new user code.
        if is_bare_expr:
            expr_src = ast.unparse(tree.body[0].value)
            # Wrap the expression so we can capture its value.
            program_parts.append(f"_repl_expr_ = {expr_src}")
            program_parts.append(
                f'print("{_SENTINEL}" + repr(_repl_expr_))')
        else:
            program_parts.append(source)

        full_source = "\n".join(program_parts)

        # --- Compile and run ---
        try:
            output, stderr, rc = self._compile_and_run(full_source)
        except Exception as e:
            return f"Compilation error: {e}"

        if rc != 0:
            # Runtime error — don't record the statement.
            msg_parts = []
            # Show any output produced before the crash.
            clean_out = self._strip_sentinels(output)
            if clean_out:
                msg_parts.append(clean_out)
            if stderr.strip():
                msg_parts.append(stderr.strip())
            msg_parts.append(f"[exit code {rc}]")
            return "\n".join(msg_parts)

        # --- Parse output ---
        # Only show output that appears AFTER the output-start sentinel.
        # This suppresses replay output (e.g. print() from previous lines).
        display_lines: list[str] = []
        expr_result = None
        past_sentinel = False

        for line in output.split("\n"):
            if line.strip() == _OUTPUT_START:
                past_sentinel = True
                continue
            if not past_sentinel:
                continue
            if line.startswith(_SENTINEL):
                expr_result = line[len(_SENTINEL):]
            elif line.strip():
                display_lines.append(line)

        # Success — record the statements in the log.
        if is_bare_expr:
            # Record bare expressions too — they may have side effects
            # (e.g. c.inc() mutates c).  The original expression (not
            # the _repl_expr_ wrapper) goes into the log.
            expr_src = ast.unparse(tree.body[0].value)
            self._statement_log.append(expr_src)
        else:
            for node in tree.body:
                stmt_src = ast.unparse(node)
                if isinstance(node, ast.FunctionDef):
                    # Deduplicate: remove previous definition of same name.
                    if node.name in self._func_def_idx:
                        old_idx = self._func_def_idx[node.name]
                        self._statement_log[old_idx] = "pass"  # placeholder
                    self._func_def_idx[node.name] = len(self._statement_log)
                    self._statement_log.append(stmt_src)
                elif isinstance(node, ast.ClassDef):
                    if node.name in self._class_def_idx:
                        old_idx = self._class_def_idx[node.name]
                        self._statement_log[old_idx] = "pass"
                    self._class_def_idx[node.name] = len(self._statement_log)
                    self._statement_log.append(stmt_src)
                else:
                    self._statement_log.append(stmt_src)

                # Track variable names.
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            self._known_vars.add(tgt.id)
                elif isinstance(node, ast.AugAssign):
                    if isinstance(node.target, ast.Name):
                        self._known_vars.add(node.target.id)

        # Build display output.
        parts: list[str] = []
        if display_lines:
            parts.append("\n".join(display_lines))
        if expr_result is not None and expr_result != "None":
            parts.append(expr_result)

        return "\n".join(parts) if parts else None

    def _strip_sentinels(self, output: str) -> str:
        """Remove sentinel lines from output, keeping only post-start content."""
        lines = output.split("\n")
        # Find the output-start sentinel and only keep lines after it.
        past_start = False
        result = []
        for line in lines:
            if line.strip() == _OUTPUT_START:
                past_start = True
                continue
            if not past_start:
                continue
            if not line.startswith(_SENTINEL) and line.strip():
                result.append(line)
        return "\n".join(result)

    def _compile_and_run(self, source: str) -> tuple[str, str, int]:
        """Compile source to an exe and run it.  Returns (stdout, stderr, rc)."""
        from compiler.pipeline import compile_source

        exe_name = f"repl_{self._line_count}.exe"
        exe_path = self._tmp_dir / exe_name

        result = compile_source(source, exe_path,
                                source_filename="<repl>")
        if not result.success:
            errors = "; ".join(str(e) for e in result.errors)
            raise RuntimeError(errors)

        proc = subprocess.run(
            [str(result.executable)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(self._tmp_dir),
        )
        return proc.stdout, proc.stderr, proc.returncode


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

def start_repl():
    """Start the interactive REPL."""
    session = ReplSession()

    print("fastpy REPL \u2014 Python compiled to native code")
    print("Type expressions, assignments, functions, classes. Ctrl+C to exit.\n")

    while True:
        try:
            line = _read_input()
            if line is None:
                break
            if line.strip() in ("exit()", "quit()"):
                break

            result = session.eval_line(line)
            if result is not None:
                print(result)

        except KeyboardInterrupt:
            print("\nKeyboardInterrupt")
        except EOFError:
            print()
            break
        except Exception as e:
            print(f"Internal error: {e}")
            traceback.print_exc()


def _read_input() -> str | None:
    """Read a possibly multi-line input from the user.

    Uses '>>> ' for the first line and '... ' for continuation lines.
    Multi-line blocks (class, def, for, if, etc.) are terminated by
    a blank line, matching Python's interactive REPL behavior.
    """
    lines: list[str] = []
    prompt = ">>> "
    in_block = False  # True once we're collecting an indented block

    while True:
        try:
            line = input(prompt)
        except EOFError:
            if lines:
                return "\n".join(lines)
            return None

        # A blank line inside a block signals end-of-block.
        if in_block and line.strip() == "":
            return "\n".join(lines)

        lines.append(line)
        source = "\n".join(lines)

        # Check if the input is complete
        try:
            ast.parse(source, mode='exec')
            # Parsed OK — but if the last line is indented or ends with
            # ':', the user is still typing a block.
            if line.strip().endswith(":") or (len(lines) > 1 and line.startswith((" ", "\t"))):
                in_block = True
                prompt = "... "
                continue
            return source
        except SyntaxError as e:
            msg = str(e).lower()
            if ("unexpected eof" in msg
                    or "expected an indented block" in msg
                    or "eof while scanning" in msg
                    or "was never closed" in msg):
                in_block = True
                prompt = "... "
                continue
            else:
                return source
