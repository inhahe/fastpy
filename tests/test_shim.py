"""
Tests for the fastpy CPython shim package (fastpy.ints).

These verify that the shim types produce correct fixed-width arithmetic
under CPython, which is the reference behavior the compiler must match.
"""

from __future__ import annotations

from fastpy import Int32, UInt32, Int64, UInt64


class TestUInt32:
    def test_wrap_on_overflow(self):
        assert int(UInt32(0xFFFFFFFF) + UInt32(1)) == 0

    def test_wrap_on_underflow(self):
        assert int(UInt32(0) - UInt32(1)) == 0xFFFFFFFF

    def test_bitwise_and(self):
        assert int(UInt32(0xFF00) & UInt32(0x0FF0)) == 0x0F00

    def test_bitwise_or(self):
        assert int(UInt32(0xFF00) | UInt32(0x00FF)) == 0xFFFF

    def test_bitwise_xor(self):
        assert int(UInt32(0xFF00) ^ UInt32(0x0FF0)) == 0xF0F0

    def test_bitwise_not(self):
        assert int(~UInt32(0)) == 0xFFFFFFFF

    def test_left_shift(self):
        assert int(UInt32(1) << 31) == 0x80000000

    def test_left_shift_overflow(self):
        assert int(UInt32(1) << 32) == 0  # shifts out entirely

    def test_right_shift(self):
        assert int(UInt32(0x80000000) >> 31) == 1

    def test_multiplication(self):
        assert int(UInt32(0x10000) * UInt32(0x10000)) == 0  # wraps

    def test_floor_division(self):
        assert int(UInt32(10) // UInt32(3)) == 3

    def test_modulo(self):
        assert int(UInt32(10) % UInt32(3)) == 1

    def test_interop_with_int(self):
        assert int(UInt32(10) + 5) == 15
        assert int(5 + UInt32(10)) == 15

    def test_comparison(self):
        assert UInt32(5) < UInt32(10)
        assert UInt32(10) > UInt32(5)
        assert UInt32(5) == UInt32(5)
        assert UInt32(5) == 5

    def test_bool(self):
        assert bool(UInt32(1)) is True
        assert bool(UInt32(0)) is False

    def test_hash(self):
        assert hash(UInt32(42)) == hash(42)

    def test_index(self):
        lst = [10, 20, 30]
        assert lst[UInt32(1)] == 20


class TestInt32:
    def test_wrap_positive_overflow(self):
        assert int(Int32(0x7FFFFFFF) + Int32(1)) == -0x80000000

    def test_wrap_negative_overflow(self):
        assert int(Int32(-0x80000000) - Int32(1)) == 0x7FFFFFFF

    def test_negation(self):
        assert int(-Int32(5)) == -5

    def test_negation_min(self):
        # Negating MIN wraps back to MIN (like C)
        assert int(-Int32(-0x80000000)) == -0x80000000

    def test_arithmetic_right_shift(self):
        # Signed right shift preserves sign
        assert int(Int32(-1) >> 1) == -1

    def test_multiplication_wrap(self):
        assert int(Int32(100000) * Int32(100000)) != 10000000000  # wraps

    def test_interop_with_int(self):
        assert int(Int32(-5) + 3) == -2
        assert int(3 + Int32(-5)) == -2


class TestUInt64:
    def test_wrap_on_overflow(self):
        assert int(UInt64(0xFFFFFFFFFFFFFFFF) + UInt64(1)) == 0

    def test_large_values(self):
        x = UInt64(1) << 63
        assert int(x) == 0x8000000000000000

    def test_bitwise(self):
        assert int(UInt64(0xDEADBEEF) & UInt64(0xFFFF0000)) == 0xDEAD0000


class TestInt64:
    def test_wrap_positive_overflow(self):
        assert int(Int64(0x7FFFFFFFFFFFFFFF) + Int64(1)) == -0x8000000000000000

    def test_range(self):
        assert Int64.MIN == -0x8000000000000000
        assert Int64.MAX == 0x7FFFFFFFFFFFFFFF

    def test_negation(self):
        assert int(-Int64(42)) == -42


class TestCrossTy:
    """Test interactions between different int types."""

    def test_repr(self):
        assert repr(UInt32(42)) == "UInt32(42)"
        assert repr(Int32(-1)) == "Int32(-1)"
        assert repr(UInt64(0)) == "UInt64(0)"
        assert repr(Int64(100)) == "Int64(100)"

    def test_str(self):
        assert str(UInt32(42)) == "42"
        assert str(Int32(-1)) == "-1"
