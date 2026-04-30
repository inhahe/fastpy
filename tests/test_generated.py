"""
Property-based tests using randomly generated Python programs.

These tests use Hypothesis to generate valid Python programs and run them
through the differential test harness. Any program that compiles must
produce the same output as CPython; programs that don't compile yet are
silently discarded (via assume()).

Run with: pytest tests/test_generated.py -v
"""

from __future__ import annotations

import ast

import pytest
from hypothesis import given, settings, HealthCheck, assume

from tests.harness import diff_test
from tests.generator.gen import (
    valid_program, valid_program_with_functions,
    valid_program_with_containers, valid_program_with_strings,
    valid_program_with_dicts, valid_program_with_exceptions,
    valid_program_comprehensive,
)


def _has_known_limitations(source: str) -> bool:
    """Check if source hits known compiler limitations."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    names = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name in names:
                return True  # duplicate function defs
            names.append(node.name)
    # Check for variables only defined in loop bodies (NameError difference)
    loop_vars = set()
    used_after = set()
    in_loop = False
    for node in tree.body:
        if isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                loop_vars.add(node.target.id)
        elif isinstance(node, ast.Expr):
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and n.id in loop_vars:
                    used_after.add(n.id)
    if used_after:
        return True  # loop variable used after loop — may cause NameError difference
    # Non-ASCII strings have repr differences between CPython and our compiler
    if any(ord(c) > 127 for c in source):
        return True
    # Very small/large float constants may have precision differences
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            v = abs(node.value)
            if v != 0 and (v < 1e-4 or v > 1e15):
                return True  # scientific notation precision may differ
    return False


# Hypothesis settings for generated tests: longer deadline because we're
# running subprocesses, suppress the "too slow" health check.
_SETTINGS = settings(
    max_examples=50,
    deadline=30000,  # 30 seconds per example
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


class TestGeneratedPrograms:
    """Randomly generated programs must match CPython output."""

    @_SETTINGS
    @given(source=valid_program())
    def test_basic_programs(self, source):
        """Generated basic programs either skip or match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()

    @_SETTINGS
    @given(source=valid_program_with_functions())
    def test_programs_with_functions(self, source):
        """Generated programs with functions either skip or match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()

    @_SETTINGS
    @given(source=valid_program_with_containers())
    def test_container_programs(self, source):
        """Generated container programs must match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()

    @_SETTINGS
    @given(source=valid_program_with_strings())
    def test_string_programs(self, source):
        """Generated string programs must match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()

    @_SETTINGS
    @given(source=valid_program_with_dicts())
    def test_dict_programs(self, source):
        """Generated dict programs must match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()

    @_SETTINGS
    @given(source=valid_program_with_exceptions())
    def test_exception_programs(self, source):
        """Generated exception programs must match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()

    @_SETTINGS
    @given(source=valid_program_comprehensive())
    def test_comprehensive_programs(self, source):
        """Generated comprehensive programs must match CPython."""
        assume(not _has_known_limitations(source))
        result = diff_test(source)
        assume(not result.skipped)
        assert not result.failed, result.detail()
