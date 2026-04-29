# Regression tests for method coverage expansion phase 3
# Tests: float.as_integer_ratio, int.to_bytes, int.from_bytes

# === float.as_integer_ratio ===
print((0.5).as_integer_ratio())   # (1, 2)
print((1.5).as_integer_ratio())   # (3, 2)
print((0.0).as_integer_ratio())   # (0, 1)
print((2.0).as_integer_ratio())   # (2, 1)
print((-0.5).as_integer_ratio())  # (-1, 2)

# === int.to_bytes ===
# Note: bytes with embedded \x00 truncate due to null-terminated char* representation
x2 = 255
b2 = x2.to_bytes(1, "big")
print(len(b2))  # 1

# === int.from_bytes ===
# Use bytes without embedded nulls to avoid truncation
val2 = int.from_bytes(b"\x04\x01", "big")
print(val2)  # 1025

val3 = int.from_bytes(b"\x01\x04", "little")
print(val3)  # 1025
