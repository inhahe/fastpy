"""
Compilation pipeline: Python source -> native executable.

Pipeline stages:
    1. Parse: source -> ast.Module (via Python's ast module)
    2. Check: verify the AST uses only supported features
    3. Codegen: ast.Module -> LLVM IR (via llvmlite)
    4. Compile + Link: LLVM IR -> native executable (via toolchain)
"""

from __future__ import annotations

import ast
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from compiler.codegen import CodeGen, CodeGenError


@dataclass
class CompileError:
    """A single compilation error."""
    message: str
    line: int | None = None
    col: int | None = None

    def __str__(self) -> str:
        loc = ""
        if self.line is not None:
            loc = f" (line {self.line}"
            if self.col is not None:
                loc += f", col {self.col}"
            loc += ")"
        return f"{self.message}{loc}"


@dataclass
class CompileResult:
    """Result of a compilation attempt."""
    success: bool
    executable: Path | None = None
    errors: list[CompileError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ir: str | None = None  # LLVM IR for debugging

    def __str__(self) -> str:
        if self.success:
            return f"Compiled successfully: {self.executable}"
        return "Compilation failed:\n" + "\n".join(f"  {e}" for e in self.errors)


def compile_source(source: str, output: Path | None = None) -> CompileResult:
    """
    Compile a Python source string to a native executable.

    Args:
        source: Python source code as a string.
        output: Path for the output executable. If None, uses a temp file.

    Returns:
        CompileResult indicating success or failure.
    """
    # Stage 1: Parse with Python's own parser
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return CompileResult(
            success=False,
            errors=[CompileError(
                message=f"SyntaxError: {e.msg}",
                line=e.lineno,
                col=e.offset,
            )],
        )

    # Stage 2: Check for unsupported features
    unsupported = _check_unsupported(tree)
    if unsupported:
        return CompileResult(
            success=False,
            errors=[CompileError(message=f"Not yet implemented: {feat}")
                    for feat in unsupported],
        )

    # Stage 3: Generate LLVM IR
    try:
        codegen = CodeGen()
        ir_string = codegen.generate(tree)
    except CodeGenError as e:
        return CompileResult(
            success=False,
            errors=[CompileError(
                message=str(e),
                line=e.node.lineno if e.node and hasattr(e.node, "lineno") else None,
            )],
        )

    # Stage 4: Compile to native executable
    if output is None:
        tmp_dir = tempfile.mkdtemp(prefix="fastpy_")
        output = Path(tmp_dir) / "output.exe"

    try:
        from compiler.toolchain import compile_and_link
        exe_path = compile_and_link(ir_string, output)
        return CompileResult(
            success=True,
            executable=exe_path,
            ir=ir_string,
        )
    except Exception as e:
        return CompileResult(
            success=False,
            errors=[CompileError(message=f"Build failed: {e}")],
            ir=ir_string,
        )


def compile_file(path: Path, output: Path | None = None) -> CompileResult:
    """Compile a Python source file to a native executable."""
    source = path.read_text(encoding="utf-8")
    return compile_source(source, output)


# ---------------------------------------------------------------------------
# Feature detection — tracks what the compiler can and can't handle yet.
# As each feature gets implemented, remove checks from _check_unsupported.
# ---------------------------------------------------------------------------

# AST node types we can handle in expressions
_SUPPORTED_EXPR_NODES = (
    ast.Constant,   # literals: 42, 3.14, "hello", True, None
    ast.UnaryOp,    # -x
    ast.BinOp,      # x + y
    ast.Call,        # print(...), range(...)
    ast.Name,        # variable references
    ast.Compare,     # x < y, x == y, etc.
    ast.BoolOp,      # x and y, x or y
)

# Statement types we can handle
_SUPPORTED_STMT_NODES = (
    ast.Expr,        # expression statement (e.g., print(...))
    ast.Assign,      # x = expr
    ast.AugAssign,   # x += expr
    ast.If,          # if/elif/else
    ast.While,       # while loop
    ast.For,         # for loop (range only for now)
    ast.Break,       # break
    ast.Continue,    # continue
    ast.Pass,        # pass (no-op)
    ast.FunctionDef, # def f(...): ...
    ast.Return,      # return expr
    ast.ClassDef,    # class Foo: ...
    ast.Try,         # try/except/finally
    ast.Raise,       # raise
    ast.Nonlocal,    # nonlocal (for closures)
    ast.Global,      # global x
    ast.Assert,      # assert
    ast.Delete,      # del
    ast.With,        # with expr as var: ...
    ast.Import,      # import module
    ast.ImportFrom,  # from module import name
    ast.Match,       # match/case (Python 3.10+)
)

# Built-in functions we can handle
_SUPPORTED_BUILTINS = {"print", "range", "len", "sorted", "int", "abs", "sum",
                       "min", "max", "list", "reversed", "set", "enumerate", "zip",
                       "isinstance", "str", "type", "any", "all", "bool", "float",
                       "chr", "ord", "hex", "oct", "bin", "round", "repr", "pow",
                       "divmod", "dict", "tuple", "map", "filter",
                       "hash", "next", "iter",
                       "bytearray", "frozenset", "complex", "slice",
                       "getattr", "setattr", "hasattr", "delattr",
                       "vars", "dir", "id", "callable", "input",
                       "open", "print", "eval", "exec",
                       "ZeroDivisionError", "ValueError", "TypeError",
                       "IndexError", "KeyError", "RuntimeError", "StopIteration",
                       "Exception", "AssertionError", "super"}


def _check_unsupported(tree: ast.Module) -> list[str]:
    """Return list of unsupported feature descriptions found in the AST."""
    found: list[str] = []

    if not tree.body:
        return found

    # Collect user-defined function, class, and lambda-assigned names
    user_functions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            user_functions.add(node.name)
        if isinstance(node, ast.ClassDef):
            user_functions.add(node.name)
        # Lambda assignments: f = lambda x: x + 1
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Lambda):
                user_functions.add(node.targets[0].id)
            # Variable assigned from a function call might be a closure
            if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
                user_functions.add(node.targets[0].id)
        # Function parameters might be callable (higher-order functions)
        if isinstance(node, ast.FunctionDef):
            for arg in node.args.args:
                # Check if this parameter is called inside the function body
                for child in ast.walk(node):
                    if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                            and child.func.id == arg.arg):
                        user_functions.add(arg.arg)
                        break

    # Collect names imported via `from module import name`
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.names:
            for alias in node.names:
                imported_names.add(alias.asname if alias.asname else alias.name)

    allowed_calls = _SUPPORTED_BUILTINS | user_functions | imported_names

    for node in ast.walk(tree):
        # Check statements
        if isinstance(node, ast.stmt) and not isinstance(node, _SUPPORTED_STMT_NODES):
            found.append(f"{type(node).__name__} statement")

        # Check that calls are only to allowed functions
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in allowed_calls:
                    found.append(f"function call: {node.func.id}()")
            elif isinstance(node.func, ast.Attribute):
                pass  # method calls like s.lower() — handled by codegen
            elif isinstance(node.func, (ast.Call, ast.Subscript)):
                pass  # C()(args) or d[key](args) — handled by codegen
            else:
                found.append(f"complex call expression")

        # BigInt: integer constants > i64 range and ** with constant args
        # that overflow are handled via compile-time constant folding.
        # No longer blocked — the codegen folds them to string constants.

    # Deduplicate
    return list(dict.fromkeys(found))
