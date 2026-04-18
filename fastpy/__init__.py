"""
fastpy — CPython-compatible shim package.

Provides opt-in machine integer types (Int32, UInt32, Int64, UInt64) that
work under CPython for development/testing and are recognized by the fastpy
compiler for native code generation.

Under CPython: wrapper classes with faithful fixed-width semantics.
Under the fastpy compiler: compiled to raw machine integers.
"""

from fastpy.ints import Int32, UInt32, Int64, UInt64

__all__ = ["Int32", "UInt32", "Int64", "UInt64"]
