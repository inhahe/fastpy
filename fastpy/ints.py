"""
Fixed-width integer types for the fastpy CPython shim.

Under CPython: wrapper classes that faithfully implement fixed-width
wraparound arithmetic via masking. Slower than native ints but
semantically correct — the output matches what the compiled version
would produce.

Under the fastpy compiler: these types are recognized at compile time
and lowered to raw machine integers with no wrapper overhead.

Types provided:
    Int32   — signed 32-bit, wraps on overflow
    UInt32  — unsigned 32-bit, wraps on overflow
    Int64   — signed 64-bit, wraps on overflow
    UInt64  — unsigned 64-bit, wraps on overflow

All types support standard arithmetic (+, -, *, //, %, **),
bitwise operations (&, |, ^, ~, <<, >>), and comparisons.
"""

from __future__ import annotations

from functools import total_ordering


def _make_int_type(
    name: str,
    bits: int,
    signed: bool,
) -> type:
    """Factory that builds a fixed-width integer wrapper class."""

    mask = (1 << bits) - 1
    if signed:
        min_val = -(1 << (bits - 1))
        max_val = (1 << (bits - 1)) - 1
    else:
        min_val = 0
        max_val = mask

    def _wrap(value: int) -> int:
        """Wrap an arbitrary Python int to the target width."""
        value = value & mask
        if signed and value > max_val:
            value -= (1 << bits)
        return value

    @total_ordering
    class FixedInt:
        __slots__ = ("_v",)

        BITS = bits
        SIGNED = signed
        MIN = min_val
        MAX = max_val

        def __init__(self, value: int | FixedInt = 0) -> None:
            if isinstance(value, FixedInt):
                self._v: int = value._v
            else:
                self._v = _wrap(int(value))

        # --- Representation ---

        def __repr__(self) -> str:
            return f"{name}({self._v})"

        def __str__(self) -> str:
            return str(self._v)

        def __int__(self) -> int:
            return self._v

        def __float__(self) -> float:
            return float(self._v)

        def __bool__(self) -> bool:
            return self._v != 0

        def __index__(self) -> int:
            return self._v

        def __hash__(self) -> int:
            return hash(self._v)

        # --- Comparison ---

        def __eq__(self, other: object) -> bool:
            if isinstance(other, FixedInt):
                return self._v == other._v
            if isinstance(other, int):
                return self._v == other
            return NotImplemented

        def __lt__(self, other: FixedInt | int) -> bool:
            if isinstance(other, FixedInt):
                return self._v < other._v
            if isinstance(other, int):
                return self._v < other
            return NotImplemented

        # --- Arithmetic ---

        def __add__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v + ov))

        def __radd__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) + self._v))

        def __sub__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v - ov))

        def __rsub__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) - self._v))

        def __mul__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v * ov))

        def __rmul__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) * self._v))

        def __floordiv__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            if ov == 0:
                raise ZeroDivisionError(f"{name} division by zero")
            # C-style truncation toward zero
            result = int(self._v / ov)
            return FixedInt(_wrap(result))

        def __rfloordiv__(self, other: int) -> FixedInt:
            if self._v == 0:
                raise ZeroDivisionError(f"{name} division by zero")
            result = int(int(other) / self._v)
            return FixedInt(_wrap(result))

        def __mod__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            if ov == 0:
                raise ZeroDivisionError(f"{name} modulo by zero")
            # C-style: result has sign of dividend
            result = self._v - int(self._v / ov) * ov
            return FixedInt(_wrap(result))

        def __rmod__(self, other: int) -> FixedInt:
            if self._v == 0:
                raise ZeroDivisionError(f"{name} modulo by zero")
            ov = int(other)
            result = ov - int(ov / self._v) * self._v
            return FixedInt(_wrap(result))

        def __neg__(self) -> FixedInt:
            return FixedInt(_wrap(-self._v))

        def __pos__(self) -> FixedInt:
            return self

        def __abs__(self) -> FixedInt:
            return FixedInt(_wrap(abs(self._v)))

        def __pow__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            if ov < 0:
                raise ValueError(f"{name} negative exponent not supported")
            return FixedInt(_wrap(self._v ** ov))

        # --- Bitwise ---

        def __and__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v & ov))

        def __rand__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) & self._v))

        def __or__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v | ov))

        def __ror__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) | self._v))

        def __xor__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v ^ ov))

        def __rxor__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) ^ self._v))

        def __invert__(self) -> FixedInt:
            return FixedInt(_wrap(~self._v))

        def __lshift__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            return FixedInt(_wrap(self._v << ov))

        def __rlshift__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) << self._v))

        def __rshift__(self, other: FixedInt | int) -> FixedInt:
            ov = other._v if isinstance(other, FixedInt) else int(other)
            # Arithmetic right shift for signed, logical for unsigned
            if signed:
                return FixedInt(self._v >> ov)
            else:
                return FixedInt(_wrap(self._v >> ov))

        def __rrshift__(self, other: int) -> FixedInt:
            return FixedInt(_wrap(int(other) >> self._v))

    # Set the class name to match the type name
    FixedInt.__name__ = name
    FixedInt.__qualname__ = name
    return FixedInt


# Build the four standard types
Int32 = _make_int_type("Int32", 32, signed=True)
UInt32 = _make_int_type("UInt32", 32, signed=False)
Int64 = _make_int_type("Int64", 64, signed=True)
UInt64 = _make_int_type("UInt64", 64, signed=False)
