"""
fastpy — CPython-compatible shim package.

Provides opt-in machine integer types (Int32, UInt32, Int64, UInt64) that
work under CPython for development/testing and are recognized by the fastpy
compiler for native code generation.

Also provides Annotated-compatible optimization markers (Unchecked, Checked)
and constructor functions (unchecked_int, checked_int) for per-variable
control over integer overflow behavior.

Under CPython: wrapper classes / plain ints with faithful semantics.
Under the fastpy compiler: compiled to raw machine integers with the
requested overflow policy.
"""

try:
    from fastpy._fastints import Int32, UInt32, Int64, UInt64
except ImportError:
    from fastpy.ints import Int32, UInt32, Int64, UInt64


# ── Annotated markers ─────────────────────────────────────────────────
# Used with typing.Annotated to control per-variable codegen:
#
#   from typing import Annotated
#   from fastpy import Unchecked, Checked
#
#   x: Annotated[int, Unchecked] = 0   # raw i64, no overflow check
#   y: Annotated[int, Checked] = 0     # overflow → OverflowError, no BigInt
#
# Under CPython these are plain classes (Annotated ignores them at runtime).
# The fastpy compiler recognizes them in annotation metadata.

class Unchecked:
    """Marker for raw 64-bit machine arithmetic with no overflow detection.

    When used as ``Annotated[int, Unchecked]``, the variable uses raw
    LLVM i64 add/sub/mul instructions.  Overflow wraps silently
    (two's-complement / C semantics).
    """


class Checked:
    """Marker for checked 64-bit arithmetic without BigInt fallback.

    When used as ``Annotated[int, Checked]``, the variable uses LLVM
    i64 overflow intrinsics.  On overflow, OverflowError is raised
    instead of promoting to BigInt.
    """


class Unchecked32:
    """Marker for raw 32-bit machine arithmetic with no overflow detection.

    When used as ``Annotated[int, Unchecked32]``, the variable uses raw
    LLVM i32 add/sub/mul instructions.  Overflow wraps silently at the
    32-bit boundary (two's-complement).  Values are stored as i64
    internally but arithmetic is performed in 32 bits.
    """


class Checked32:
    """Marker for checked 32-bit arithmetic without BigInt fallback.

    When used as ``Annotated[int, Checked32]``, the variable uses LLVM
    i32 overflow intrinsics.  On overflow, OverflowError is raised.
    Values are stored as i64 internally but arithmetic is performed
    in 32 bits.
    """


# ── Constructor functions ─────────────────────────────────────────────
# Alternative to Annotated markers — the constructor marks the *result*
# variable with the requested overflow policy:
#
#   x = unchecked_int(42)     # same as Annotated[int, Unchecked]
#   y = checked_int(42)       # same as Annotated[int, Checked]
#   a = unchecked_int32(42)   # same as Annotated[int, Unchecked32]
#   b = checked_int32(42)     # same as Annotated[int, Checked32]
#
# Under CPython: i64 variants return int(x); i32 variants wrap/clamp
# to the 32-bit signed range so behaviour matches the compiler.

def unchecked_int(x=0):
    """Return x as a plain int.  Under the fastpy compiler, marks the
    assignment target for raw i64 arithmetic (no overflow check)."""
    return int(x)


def checked_int(x=0):
    """Return x as a plain int.  Under the fastpy compiler, marks the
    assignment target for checked i64 arithmetic (OverflowError on
    overflow, no BigInt promotion)."""
    return int(x)


def unchecked_int32(x=0):
    """Return x wrapped to the signed i32 range ``[-2**31, 2**31 - 1]``.

    Under the fastpy compiler, marks the assignment target for raw i32
    arithmetic (wraps silently at the 32-bit boundary).
    """
    x = int(x)
    x = ((x + 0x80000000) % 0x100000000) - 0x80000000
    return x


def checked_int32(x=0):
    """Return x wrapped to the signed i32 range ``[-2**31, 2**31 - 1]``.

    Under the fastpy compiler, marks the assignment target for checked
    i32 arithmetic (OverflowError on overflow).
    """
    x = int(x)
    x = ((x + 0x80000000) % 0x100000000) - 0x80000000
    return x


__all__ = [
    "Int32", "UInt32", "Int64", "UInt64",
    "Unchecked", "Checked", "Unchecked32", "Checked32",
    "unchecked_int", "checked_int", "unchecked_int32", "checked_int32",
]
