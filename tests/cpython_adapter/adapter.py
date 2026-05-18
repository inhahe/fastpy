"""
Adapter: transforms raw CPython test files into self-contained programs
suitable for fastpy differential testing.

Two modes:
  1. "stdlib" — inlines the pure-Python stdlib module source (stripped of
     C-extension fallbacks) and generates a test program that exercises
     it via direct function calls.
  2. "language" — strips test.support/unittest boilerplate and generates
     a test program exercising language features directly.

The output is a single .py file that:
  - Both CPython and fastpy can compile/run
  - Prints deterministic output (PASS/FAIL per test function)
  - Contains all needed code inline (no imports except builtins)
  - Uses NO classes — only module-level functions (avoids fastpy scoping
    issues with class methods referencing module-level names)
"""

from __future__ import annotations

import ast
import copy
import sys
import textwrap
from pathlib import Path
from typing import Optional

# Local Python stdlib path
_STDLIB_DIR = Path(sys.prefix) / "Lib"

# Standard assertion helpers that replace unittest.TestCase methods
_ASSERT_HELPERS = '''\
# Assertion helpers (replacing unittest.TestCase methods)
def assertEqual(a, b, msg=None):
    if a != b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b))

def assertNotEqual(a, b, msg=None):
    if a == b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b))

def assertAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) > 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b) + " within " + str(places) + " places")

def assertNotAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) <= 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b) + " within " + str(places) + " places")

def assertTrue(x, msg=None):
    if not x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected True, got " + str(x))

def assertFalse(x, msg=None):
    if x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected False, got " + str(x))

def assertIs(a, b, msg=None):
    if a is not b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not " + str(b))

def assertIsNot(a, b, msg=None):
    if a is b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is " + str(b))

def assertIsNone(x, msg=None):
    if x is not None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(x) + " is not None")

def assertIsNotNone(x, msg=None):
    if x is None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("unexpected None")

def assertIn(a, b, msg=None):
    if a not in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not in " + str(b))

def assertNotIn(a, b, msg=None):
    if a in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " in " + str(b))

def assertIsInstance(a, b, msg=None):
    if not isinstance(a, b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not instance of " + str(b))

def assertGreater(a, b, msg=None):
    if not (a > b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not greater than " + str(b))

def assertGreaterEqual(a, b, msg=None):
    if not (a >= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not >= " + str(b))

def assertLess(a, b, msg=None):
    if not (a < b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not less than " + str(b))

def assertLessEqual(a, b, msg=None):
    if not (a <= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not <= " + str(b))

def assertSequenceEqual(a, b, msg=None):
    if len(a) != len(b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError("sequences differ in length: " + str(len(a)) + " vs " + str(len(b)))
    for i in range(len(a)):
        if a[i] != b[i]:
            if msg:
                raise AssertionError(msg)
            raise AssertionError("sequences differ at index " + str(i) + ": " + str(a[i]) + " != " + str(b[i]))

def assertListEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)

def assertTupleEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)
'''


def adapt_stdlib_test(
    raw_test_source: str,
    module_name: str,
    *,
    skip_methods: Optional[set[str]] = None,
    skip_classes: Optional[set[str]] = None,
) -> Optional[str]:
    """Adapt a CPython stdlib test by inlining the pure-Python module source.

    Returns the adapted source string, or None if adaptation fails.
    """
    skip_methods = skip_methods or set()
    skip_classes = skip_classes or set()

    # Step 1: Read and clean the stdlib module source
    stdlib_source = _get_stdlib_source(module_name)
    if stdlib_source is None:
        return None

    # Step 2: Parse the test file and extract test classes/methods
    try:
        tree = ast.parse(raw_test_source)
    except SyntaxError:
        return None

    test_classes = _extract_test_classes(tree, skip_methods, skip_classes)
    if not test_classes:
        return None

    # Step 3: Build the adapted program
    lines = []
    lines.append(f"# Auto-adapted from CPython Lib/test/test_{module_name}.py")
    lines.append(f"# Tests fastpy's ability to compile and run the {module_name} module")
    lines.append(f"# Stdlib source inlined from: {_STDLIB_DIR / (module_name + '.py')}")
    lines.append("")
    lines.append("# " + "=" * 70)
    lines.append(f"# Inlined stdlib module: {module_name}")
    lines.append("# " + "=" * 70)
    lines.append("")
    lines.append(stdlib_source)
    lines.append("")

    # Step 3b: Assertion helpers
    lines.append("# " + "=" * 70)
    lines.append("# Assertion helpers")
    lines.append("# " + "=" * 70)
    lines.append("")
    lines.append(_ASSERT_HELPERS)
    lines.append("")

    # Step 3c: Include helper functions/classes from the test file
    helpers = _extract_helpers(tree, skip_classes)
    if helpers:
        lines.append("# " + "=" * 70)
        lines.append("# Helper functions from test file")
        lines.append("# " + "=" * 70)
        lines.append("")
        lines.append(helpers)
        lines.append("")

    lines.append("# " + "=" * 70)
    lines.append("# Test functions (extracted from CPython test suite)")
    lines.append("# " + "=" * 70)
    lines.append("")

    # Step 4: Emit test functions (extracted from class methods, de-selfed)
    all_test_funcs = []
    for cls_name, methods in test_classes:
        funcs = _emit_test_functions(cls_name, methods, module_name, raw_test_source)
        lines.append(funcs)
        lines.append("")
        for method_name in methods:
            all_test_funcs.append(f"{cls_name}__{method_name}")

    # Step 5: Emit direct invocation
    lines.append("# " + "=" * 70)
    lines.append("# Direct invocation")
    lines.append("# " + "=" * 70)
    lines.append("")
    for func_name in all_test_funcs:
        # Format display name: TestClass.test_method
        parts = func_name.split("__", 1)
        display_name = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else func_name
        lines.append(f"try:")
        lines.append(f"    {func_name}()")
        lines.append(f'    print("{display_name}: PASS")')
        lines.append(f"except Exception as _e:")
        lines.append(f'    print("{display_name}: FAIL -", _e)')

    return "\n".join(lines)


def adapt_language_test(
    raw_test_source: str,
    test_name: str,
    *,
    skip_methods: Optional[set[str]] = None,
    skip_classes: Optional[set[str]] = None,
) -> Optional[str]:
    """Adapt a CPython language-feature test (no stdlib inlining needed).

    Returns the adapted source string, or None if adaptation fails.
    """
    skip_methods = skip_methods or set()
    skip_classes = skip_classes or set()

    try:
        tree = ast.parse(raw_test_source)
    except SyntaxError:
        return None

    test_classes = _extract_test_classes(tree, skip_methods, skip_classes)
    if not test_classes:
        return None

    lines = []
    lines.append(f"# Auto-adapted from CPython Lib/test/{test_name}.py")
    lines.append(f"# Tests Python language features via fastpy compilation")
    lines.append("")

    # Assertion helpers
    lines.append(_ASSERT_HELPERS)
    lines.append("")

    # Emit helper functions/classes from top-level (not test classes)
    helpers = _extract_helpers(tree, skip_classes)
    if helpers:
        lines.append("# Helper definitions from test file")
        lines.append(helpers)
        lines.append("")

    # Emit test functions
    all_test_funcs = []
    for cls_name, methods in test_classes:
        funcs = _emit_test_functions(cls_name, methods, None, raw_test_source)
        lines.append(funcs)
        lines.append("")
        for method_name in methods:
            all_test_funcs.append(f"{cls_name}__{method_name}")

    # Direct invocation
    lines.append("# Direct invocation")
    for func_name in all_test_funcs:
        parts = func_name.split("__", 1)
        display_name = f"{parts[0]}.{parts[1]}" if len(parts) == 2 else func_name
        lines.append(f"try:")
        lines.append(f"    {func_name}()")
        lines.append(f'    print("{display_name}: PASS")')
        lines.append(f"except Exception as _e:")
        lines.append(f'    print("{display_name}: FAIL -", _e)')
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_stdlib_source(module_name: str) -> Optional[str]:
    """Read and clean the stdlib module source (strip C-extension fallback)."""
    module_path = _STDLIB_DIR / f"{module_name}.py"
    if not module_path.exists():
        # Try as package
        module_path = _STDLIB_DIR / module_name / "__init__.py"
        if not module_path.exists():
            return None

    source = module_path.read_text(encoding="utf-8", errors="replace")

    # Strip the C-extension fallback pattern at the end:
    #   try:
    #       from _bisect import *
    #   except ImportError:
    #       pass
    lines = source.splitlines()
    cleaned = _strip_c_extension_imports(lines)

    # Strip `if __name__ == '__main__':` block
    cleaned = _strip_main_block(cleaned)

    # Strip imports of other stdlib modules that might cause issues
    # (keep them as comments for reference)
    result = "\n".join(cleaned)
    return result


def _strip_c_extension_imports(lines: list[str]) -> list[str]:
    """Remove 'from _<module> import *' try/except blocks."""
    result = []
    i = 0
    while i < len(lines):
        # Detect pattern:
        #   try:
        #       from _xxx import *
        #   except ImportError:
        #       pass
        if (i + 3 < len(lines)
                and lines[i].strip() == "try:"
                and "from _" in lines[i + 1]
                and "import *" in lines[i + 1]):
            # Skip the entire try/except block
            j = i + 2
            while j < len(lines) and (
                lines[j].strip().startswith("except")
                or lines[j].strip() == "pass"
                or lines[j].strip() == ""
                or lines[j].startswith("    ")
                or lines[j].startswith("\t")
            ):
                if (lines[j].strip().startswith("except")
                        or lines[j].strip() == "pass"):
                    j += 1
                    # Skip any indented block under except
                    while j < len(lines) and (
                        lines[j].startswith("    ")
                        or lines[j].startswith("\t")
                        or lines[j].strip() == ""
                    ):
                        j += 1
                    break
                j += 1
            result.append(f"# [stripped C-extension import from line {i + 1}]")
            i = j
        else:
            result.append(lines[i])
            i += 1
    return result


def _strip_main_block(lines: list[str]) -> list[str]:
    """Remove `if __name__ == '__main__':` block at end of file."""
    result = []
    i = 0
    while i < len(lines):
        if (lines[i].strip().startswith("if __name__")
                and "__main__" in lines[i]):
            # Skip everything from here to end (or until dedent)
            break
        result.append(lines[i])
        i += 1
    return result


def _extract_test_classes(
    tree: ast.Module,
    skip_methods: set[str],
    skip_classes: set[str],
) -> list[tuple[str, list[str]]]:
    """Extract (class_name, [method_names]) from unittest.TestCase classes.

    Handles CPython's mixin pattern where:
      TestBisect — contains test methods (no TestCase base)
      TestBisectPython(TestBisect, unittest.TestCase) — empty body
    In this case we return the concrete class (TestBisectPython) with
    methods inherited from the mixin.
    """
    # First pass: collect all classes and their direct methods
    all_classes: dict[str, ast.ClassDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            all_classes[node.name] = node

    result = []
    for node in all_classes.values():
        if node.name in skip_classes:
            continue

        # Check if it inherits from unittest.TestCase (directly or transitively)
        has_testcase_base = False
        mixin_bases: list[str] = []
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Attribute):
                # unittest.TestCase
                base_name = base.attr
                if base_name == "TestCase":
                    has_testcase_base = True
                    continue
            elif isinstance(base, ast.Name):
                base_name = base.id
                # Direct reference to TestCase (from `from unittest import TestCase`)
                if base_name == "TestCase":
                    has_testcase_base = True
                    continue
            # If the base is defined in this file, it's a mixin/parent
            if base_name and base_name in all_classes:
                mixin_bases.append(base_name)
                # Check if the parent itself inherits from TestCase (transitively)
                parent = all_classes[base_name]
                for pbase in parent.bases:
                    pname = getattr(pbase, 'id', '') or getattr(pbase, 'attr', '')
                    if pname == "TestCase":
                        has_testcase_base = True
                    elif pname in all_classes:
                        # Check one more level (BaseTestCase -> TestCase)
                        gparent = all_classes.get(pname)
                        if gparent:
                            for gpbase in gparent.bases:
                                gpname = getattr(gpbase, 'id', '') or getattr(gpbase, 'attr', '')
                                if gpname == "TestCase":
                                    has_testcase_base = True

        if not has_testcase_base:
            continue

        # Collect methods: first from this class directly, then from mixins
        methods = []
        seen = set()

        # Methods from mixin bases (where CPython typically puts them)
        for mixin_name in mixin_bases:
            if mixin_name in skip_classes:
                continue
            mixin_cls = all_classes.get(mixin_name)
            if mixin_cls is None:
                continue
            for item in mixin_cls.body:
                if (isinstance(item, ast.FunctionDef)
                        and item.name.startswith("test_")
                        and item.name not in skip_methods
                        and item.name not in seen):
                    if not _method_uses_unsupported(item):
                        methods.append(item.name)
                        seen.add(item.name)

        # Methods defined directly on this class
        for item in node.body:
            if (isinstance(item, ast.FunctionDef)
                    and item.name.startswith("test_")
                    and item.name not in skip_methods
                    and item.name not in seen):
                if not _method_uses_unsupported(item):
                    methods.append(item.name)
                    seen.add(item.name)

        if methods:
            result.append((node.name, methods))
    return result


def _method_uses_unsupported(node: ast.FunctionDef) -> bool:
    """Check if a test method uses features that make it unadaptable."""
    source_fragment = ast.unparse(node)
    # Skip methods using subTest, skipTest, async, contextmanager, etc.
    unsupported_patterns = [
        "subTest", "skipTest", "skipIf", "expectedFailure",
        "assertWarns", "assertLogs", "assertRaises",
        "assertCountEqual", "assertRegex",
        "sys.maxsize", "sys.getrecursionlimit", "sys.hash_info",
        "__sizeof__", "__format__",
        "pickle", "copy.deepcopy",
        "gc.collect", "weakref",
        "random.", "UserList", "operator.",
        "threading", "multiprocessing",
        "mock.", "patch(",
        "importlib", "tempfile", "os.environ",
    ]
    for pattern in unsupported_patterns:
        if pattern in source_fragment:
            return True
    # Skip methods with decorators other than basic ones
    for dec in node.decorator_list:
        dec_str = ast.dump(dec)
        if "skip" in dec_str.lower() or "expected" in dec_str.lower():
            return True
    return False


def _extract_helpers(tree: ast.Module, skip_classes: set[str] = None) -> str:
    """Extract non-test, non-import top-level definitions.

    Returns standalone functions and non-TestCase classes.
    """
    skip_classes = skip_classes or set()
    lines = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test_"):
                lines.append(ast.unparse(node))
                lines.append("")
        elif isinstance(node, ast.ClassDef):
            if node.name in skip_classes:
                continue
            # Include non-TestCase classes as helpers
            is_test = any(
                "Test" in (getattr(b, 'attr', '') or getattr(b, 'id', ''))
                for b in node.bases
            )
            if not is_test and not node.name.startswith("Test"):
                lines.append(ast.unparse(node))
                lines.append("")
    return "\n".join(lines) if lines else ""


def _emit_test_functions(
    cls_name: str,
    methods: list[str],
    module_name: Optional[str],
    raw_source: str,
) -> str:
    """Emit standalone test functions extracted from a TestCase class.

    Transforms class methods into module-level functions by:
    - Removing `self` parameter
    - Replacing `self.assertEqual(...)` → `assertEqual(...)`
    - Replacing `self.module.func(...)` → `func(...)`
    - Replacing `self.<helper>(...)` → `<helper>(...)`
    - Prefixing function names with ClassName__ for uniqueness
    """
    try:
        tree = ast.parse(raw_source)
    except SyntaxError:
        return f"# Could not parse source for {cls_name}"

    # Collect all class definitions
    all_classes: dict[str, ast.ClassDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            all_classes[node.name] = node

    target = all_classes.get(cls_name)
    if target is None:
        return f"# Class {cls_name} not found in source"

    # Find mixin/parent bases to pull methods from
    mixin_names = []
    for base in target.bases:
        base_name = ""
        if isinstance(base, ast.Name):
            base_name = base.id
        elif isinstance(base, ast.Attribute):
            base_name = base.attr
        # Include any parent class defined in this file (except unittest.TestCase itself)
        if base_name and base_name in all_classes and base_name != "TestCase":
            mixin_names.append(base_name)
            # Also include grandparent classes (BaseTestCase -> TestCase chain)
            grandparent = all_classes[base_name]
            for gpbase in grandparent.bases:
                gpname = getattr(gpbase, 'id', '') or getattr(gpbase, 'attr', '')
                if gpname in all_classes and gpname != "TestCase" and gpname not in mixin_names:
                    mixin_names.append(gpname)

    # Collect method AST nodes
    method_set = set(methods)
    func_parts = []
    emitted = set()

    # Helper methods (non-test, non-dunder) from mixin bases and target class
    # These become module-level helper functions
    # Note: module_aliases will be populated later from setUp, but we process
    # helpers after setUp detection (see below)
    helper_sources = []
    for source_cls in [all_classes[m] for m in mixin_names if m in all_classes] + [target]:
        for item in source_cls.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if (not item.name.startswith("test_")
                    and not item.name.startswith("__")
                    and item.name not in emitted
                    and item.name != "setUp"
                    and item.name != "setUpClass"):
                helper_sources.append(item)
                emitted.add(item.name)

    # setUp methods — detect module aliases and extract non-alias setup code
    setup_func = None
    module_aliases = set()
    if module_name:
        module_aliases.add(module_name)
    module_aliases.add("module")  # default alias from self.module pattern

    for source_cls in [all_classes[m] for m in mixin_names if m in all_classes] + [target]:
        for item in source_cls.body:
            if isinstance(item, ast.FunctionDef) and item.name == "setUp":
                # Pre-scan setUp for module aliases (self.module = X, mod = self.module)
                for stmt in item.body:
                    if isinstance(stmt, ast.Assign):
                        # self.module = X pattern
                        for t in stmt.targets:
                            if (isinstance(t, ast.Attribute)
                                    and isinstance(t.value, ast.Name)
                                    and t.value.id == "self"
                                    and t.attr == "module"):
                                # Track what's being assigned (the module name)
                                if isinstance(stmt.value, ast.Name):
                                    module_aliases.add(stmt.value.id)
                            # mod = self.module pattern
                            elif isinstance(t, ast.Name):
                                if (isinstance(stmt.value, ast.Attribute)
                                        and isinstance(stmt.value.value, ast.Name)
                                        and stmt.value.value.id == "self"
                                        and stmt.value.attr == "module"):
                                    module_aliases.add(t.id)
                setup_func = _deself_method(item, module_name, module_aliases=module_aliases)
                break
        if setup_func is not None:
            break

    # Filter setUp body: remove Pass nodes (which are stripped module assignments)
    if setup_func is not None:
        setup_func.body = [s for s in setup_func.body if not isinstance(s, ast.Pass)]
        if not setup_func.body:
            setup_func = None  # setUp was ONLY module alias assignments

    # Now process helper methods (after module_aliases is fully populated)
    helper_funcs = []
    for item in helper_sources:
        helper_func = _deself_method(item, module_name, module_aliases=module_aliases)
        if helper_func is not None:
            helper_funcs.append(ast.unparse(helper_func))

    # Test methods from mixin bases and target class
    for source_cls in [all_classes[m] for m in mixin_names if m in all_classes] + [target]:
        for item in source_cls.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name in method_set and item.name not in emitted:
                func = _deself_method(item, module_name, module_aliases=module_aliases)
                if func is not None:
                    # Rename to ClassName__method_name for uniqueness
                    func.name = f"{cls_name}__{item.name}"
                    # If there's a setUp, inject its body at the start
                    if setup_func is not None:
                        setup_body = copy.deepcopy(setup_func.body)
                        func.body = setup_body + func.body
                    # Strip any Pass nodes from the function body
                    func.body = [s for s in func.body if not isinstance(s, ast.Pass)]
                    func_parts.append(ast.unparse(func))
                    emitted.add(item.name)

    if not func_parts and not helper_funcs:
        return f"# Class {cls_name}: no adaptable methods"

    result_lines = []
    if helper_funcs:
        result_lines.append(f"# Helper methods from {cls_name}")
        for hf in helper_funcs:
            result_lines.append(hf)
            result_lines.append("")

    result_lines.append(f"# Test functions from {cls_name}")
    for fp in func_parts:
        result_lines.append(fp)
        result_lines.append("")

    return "\n".join(result_lines)


def _deself_method(
    node: ast.FunctionDef,
    module_name: Optional[str],
    module_aliases: Optional[set[str]] = None,
) -> Optional[ast.FunctionDef]:
    """Transform a class method into a standalone function.

    - Removes `self` from parameters
    - Replaces `self.assertEqual(a, b)` → `assertEqual(a, b)`
    - Replaces `self.module.func(...)` → `func(...)`
    - Replaces `self.<attr>` access → local variable (where feasible)
    - Strips module alias assignments (e.g., `mod = module`)
    """
    func = copy.deepcopy(node)

    # Remove `self` from args
    if func.args.args and func.args.args[0].arg == "self":
        func.args.args = func.args.args[1:]

    # Remove decorators (they're typically unittest-related)
    func.decorator_list = []

    # AST transform: replace self.X references
    transformer = _DeSelfTransformer(module_name, module_aliases=module_aliases)
    func = transformer.visit(func)
    ast.fix_missing_locations(func)

    return func


class _DeSelfTransformer(ast.NodeTransformer):
    """AST transformer that removes `self.` references from method bodies.

    Also handles module reference aliases:
    - `self.module.X` → `X`
    - `module.X` → `X` (after setUp de-selfing creates `module = bisect`)
    - `mod.X` → `X` (after `mod = self.module` is de-selfed)
    """

    def __init__(self, module_name: Optional[str], module_aliases: Optional[set[str]] = None):
        self.module_name = module_name
        # Names that are aliases for the module (e.g., "module", "mod")
        self.module_aliases = module_aliases or set()
        if module_name:
            self.module_aliases.add(module_name)
        # Always treat bare "module" as a module alias (common setUp pattern)
        self.module_aliases.add("module")

    def _is_module_ref(self, node: ast.expr) -> bool:
        """Check if a node is a reference to the module."""
        if isinstance(node, ast.Name):
            return node.id in self.module_aliases
        return False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        # First recurse into children
        self.generic_visit(node)

        # self.assertEqual(a, b) → assertEqual(a, b)
        # self.module.func(a) → func(a)
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                # self.X(...) → X(...)
                node.func = ast.Name(id=node.func.attr, ctx=ast.Load())
            elif (isinstance(node.func.value, ast.Attribute)
                  and isinstance(node.func.value.value, ast.Name)
                  and node.func.value.value.id == "self"
                  and node.func.value.attr == "module"):
                # self.module.func(...) → func(...)
                node.func = ast.Name(id=node.func.attr, ctx=ast.Load())
            elif self._is_module_ref(node.func.value):
                # module.func(...) / mod.func(...) / bisect.func(...) → func(...)
                node.func = ast.Name(id=node.func.attr, ctx=ast.Load())

        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        # First recurse into children
        self.generic_visit(node)

        # self.X → X (for simple attribute access, not calls)
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            # self.X → X
            return ast.Name(id=node.attr, ctx=node.ctx)
        elif (isinstance(node.value, ast.Attribute)
              and isinstance(node.value.value, ast.Name)
              and node.value.value.id == "self"
              and node.value.attr == "module"):
            # self.module.X → X
            return ast.Name(id=node.attr, ctx=node.ctx)

        # module_ref.X → X
        if self._is_module_ref(node.value):
            return ast.Name(id=node.attr, ctx=node.ctx)

        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        """Strip module alias assignments and self-referencing assignments.

        Detects patterns like:
          module = bisect  (from setUp: self.module = bisect)
          mod = module     (from setUp: mod = self.module)
          bisect_left = bisect_left  (from: x = self.module.bisect_left after transform)
        """
        self.generic_visit(node)

        # Check if RHS is a module reference
        if isinstance(node.value, ast.Name) and node.value.id in self.module_aliases:
            # LHS = module_ref → track the LHS as another alias and strip
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.module_aliases.add(target.id)
            # Return a pass statement (effectively strips the assignment)
            return ast.Pass()

        # Check if RHS is the module name itself (from setUp: self.module = bisect)
        if (self.module_name
                and isinstance(node.value, ast.Name)
                and node.value.id == self.module_name):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.module_aliases.add(target.id)
            return ast.Pass()

        # Strip self-referencing assignments: x = x
        # (These arise from `x = self.module.x` → after transform `x = x`)
        if (len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Name)
                and node.targets[0].id == node.value.id):
            return ast.Pass()

        return node
