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


def compile_source(source: str, output: Path | None = None,
                   threading_mode: int = 0,
                   int64_mode: bool = False) -> CompileResult:
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
        codegen = CodeGen(threading_mode=threading_mode, int64_mode=int64_mode)
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


def compile_file(path: Path, output: Path | None = None,
                 threading_mode: int = 0,
                 int64_mode: bool = False) -> CompileResult:
    """Compile a Python source file to a native executable.

    Resolves local imports: if the source contains `import foo` or
    `from foo import bar` and `foo.py` (or `foo/__init__.py`) exists
    relative to the source file, the imported module is compiled inline.
    External imports (stdlib, third-party) route through CPython bridge.
    """
    source = path.read_text(encoding="utf-8")
    base_dir = path.resolve().parent

    # Resolve local imports and merge into a single source
    merged = _resolve_and_merge(source, base_dir)

    return compile_source(merged, output, threading_mode=threading_mode,
                          int64_mode=int64_mode)


def _resolve_and_merge(source: str, base_dir: Path,
                        _visited: set | None = None,
                        _current_pkg: str = "") -> str:
    """Recursively resolve local imports and merge modules into one source.

    For each `import X` or `from X import Y` where X.py exists locally:
    1. Parse X.py, prefix its top-level names with `modname__` to avoid collisions
    2. Prepend the prefixed module code before the importing module
    3. Replace the import statement with aliasing assignments

    Handles: `from X import Y`, `import X` (dotted access), relative imports,
    package imports (`from pkg.mod import func`), name collision avoidance.
    """
    if _visited is None:
        _visited = set()

    tree = ast.parse(source)
    imports_to_resolve: list[tuple[int, ast.stmt, str, Path]] = []

    for i, node in enumerate(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_path = _find_local_module(alias.name, base_dir)
                if mod_path is not None:
                    imports_to_resolve.append((i, node, alias.name, mod_path))
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            # Handle relative imports: from . import X or from .mod import Y
            if node.level and node.level > 0:
                # Relative import — resolve from current package directory
                rel_base = base_dir
                for _ in range(node.level - 1):
                    rel_base = rel_base.parent
                if mod_name:
                    mod_path = _find_local_module(mod_name, rel_base)
                else:
                    # from . import X — look for X.py in current dir
                    for alias in node.names:
                        p = _find_local_module(alias.name, rel_base)
                        if p is not None:
                            imports_to_resolve.append((i, node, alias.name, p))
                    continue
                if mod_path is not None:
                    imports_to_resolve.append((i, node, mod_name, mod_path))
            elif mod_name:
                mod_path = _find_local_module(mod_name, base_dir)
                if mod_path is not None:
                    imports_to_resolve.append((i, node, mod_name, mod_path))

    if not imports_to_resolve:
        return source

    prepended_sources: list[str] = []
    import_indices_to_remove: set[int] = set()
    # Maps local_name → prefixed_name for direct rewriting in the main source
    all_name_maps: dict[str, str] = {}

    for idx, node, mod_name, mod_path in imports_to_resolve:
        mod_key = str(mod_path.resolve())
        safe_prefix = mod_name.replace(".", "_")

        if mod_key not in _visited:
            _visited.add(mod_key)
            mod_source = mod_path.read_text(encoding="utf-8")
            mod_base = mod_path.parent
            resolved_mod = _resolve_and_merge(mod_source, mod_base, _visited)
            resolved_mod = _strip_main_block(resolved_mod)
            prefixed_mod = _prefix_module_defs(resolved_mod, safe_prefix)
            prepended_sources.append(prefixed_mod)

        import_indices_to_remove.add(idx)
        name_map = _generate_name_map(node, mod_name, safe_prefix)
        all_name_maps.update(name_map)

    # Collect local module names for dotted-access rewriting
    local_modules: dict[str, str] = {}  # module_var → prefix
    for idx, node, mod_name, mod_path in imports_to_resolve:
        if isinstance(node, ast.Import):
            for alias in node.names:
                var = alias.asname if alias.asname else alias.name
                safe = mod_name.replace(".", "_")
                local_modules[var] = safe

    # Build the remaining body: skip resolved imports, keep everything else
    new_body: list[ast.stmt] = []
    for i, stmt in enumerate(tree.body):
        if i not in import_indices_to_remove:
            new_body.append(stmt)

    # Rewrite names: imported names → prefixed names, dotted access → prefixed
    if all_name_maps or local_modules:
        class ImportRewriter(ast.NodeTransformer):
            def visit_Name(self, node):
                if node.id in all_name_maps:
                    node.id = all_name_maps[node.id]
                return node
            def visit_Attribute(self, node):
                self.generic_visit(node)
                if (isinstance(node.value, ast.Name)
                        and node.value.id in local_modules):
                    pfx = local_modules[node.value.id]
                    return ast.Name(id=f"{pfx}__{node.attr}", ctx=node.ctx)
                return node
        wrapper = ast.Module(body=new_body, type_ignores=[])
        wrapper = ImportRewriter().visit(wrapper)
        ast.fix_missing_locations(wrapper)
        new_body = wrapper.body

    main_source = ast.unparse(ast.Module(body=new_body, type_ignores=[]))
    merged = '\n'.join(prepended_sources) + '\n' + main_source
    return merged


def _prefix_module_defs(source: str, prefix: str) -> str:
    """Prefix all top-level function and class definitions with `prefix__`.

    `def foo():` → `def prefix__foo():`
    `class Bar:` → `class prefix__Bar:`
    Also renames references within the module to use the prefixed names.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    # Collect top-level names to prefix
    top_names: dict[str, str] = {}  # old_name → new_name
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            top_names[node.name] = f"{prefix}__{node.name}"
        elif isinstance(node, ast.ClassDef):
            top_names[node.name] = f"{prefix}__{node.name}"
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name):
                top_names[node.targets[0].id] = f"{prefix}__{node.targets[0].id}"

    if not top_names:
        return source

    # Rename all references
    class NamePrefixer(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in top_names:
                node.id = top_names[node.id]
            return node
        def visit_FunctionDef(self, node):
            if node.name in top_names:
                node.name = top_names[node.name]
            self.generic_visit(node)
            return node
        def visit_ClassDef(self, node):
            if node.name in top_names:
                node.name = top_names[node.name]
            self.generic_visit(node)
            return node

    tree = NamePrefixer().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _generate_name_map(node: ast.stmt, mod_name: str,
                        prefix: str) -> dict[str, str]:
    """Generate a mapping from local names to prefixed names.

    `from X import foo, bar` → {'foo': 'X__foo', 'bar': 'X__bar'}
    `from X import foo as f` → {'f': 'X__foo'}
    """
    name_map: dict[str, str] = {}
    if isinstance(node, ast.ImportFrom):
        for alias in node.names:
            local = alias.asname if alias.asname else alias.name
            name_map[local] = f"{prefix}__{alias.name}"
    return name_map


def _find_local_module(module_name: str, base_dir: Path) -> Path | None:
    """Find a local .py file for the given module name.

    Checks:
      - base_dir/module_name.py
      - base_dir/module_name/__init__.py
      - base_dir/parts[0]/parts[1]/...py (for dotted names)
    """
    parts = module_name.split('.')
    # Direct file: foo.py
    candidate = base_dir / (parts[0] + '.py')
    if len(parts) == 1 and candidate.is_file():
        return candidate
    # Package: foo/__init__.py
    candidate = base_dir / parts[0] / '__init__.py'
    if len(parts) == 1 and candidate.is_file():
        return candidate
    # Dotted: foo/bar.py or foo/bar/__init__.py
    if len(parts) > 1:
        rel = Path(*parts[:-1]) / (parts[-1] + '.py')
        candidate = base_dir / rel
        if candidate.is_file():
            return candidate
        rel = Path(*parts) / '__init__.py'
        candidate = base_dir / rel
        if candidate.is_file():
            return candidate
    return None


def _strip_main_block(source: str) -> str:
    """Remove `if __name__ == '__main__':` blocks from imported module source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    new_body = []
    for node in tree.body:
        if (isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == '__name__'):
            continue  # Skip if __name__ == '__main__' block
        new_body.append(node)
    if len(new_body) == len(tree.body):
        return source  # No change
    return ast.unparse(ast.Module(body=new_body, type_ignores=[]))


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
    ast.AnnAssign,   # x: int = expr (type-annotated assignment)
    ast.AsyncFunctionDef,  # async def (routed through CPython bridge)
    ast.TryStar,     # except* (exception groups, Python 3.11+)
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
                       "open", "print", "eval", "exec", "locals", "globals",
                       "compile", "staticmethod", "classmethod", "property",
                       "object", "issubclass", "enumerate", "reversed",
                       "NotImplemented", "Ellipsis", "__import__",
                       "ZeroDivisionError", "ValueError", "TypeError",
                       "IndexError", "KeyError", "RuntimeError", "StopIteration",
                       "AttributeError", "NotImplementedError", "FileNotFoundError",
                       "OverflowError", "GeneratorExit", "OSError", "IOError",
                       "Exception", "AssertionError", "ExceptionGroup", "super"}


def _check_unsupported(tree: ast.Module) -> list[str]:
    """Return list of unsupported feature descriptions found in the AST."""
    found: list[str] = []

    if not tree.body:
        return found

    # Collect user-defined function, class, and lambda-assigned names
    user_functions = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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
