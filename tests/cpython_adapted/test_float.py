# Adapted from CPython Lib/test/test_float.py
# Tests float operations

# Basic arithmetic
print(1.5 + 2.5)
print(10.0 - 3.5)
print(2.5 * 4.0)
print(7.5 / 2.5)
print(7.5 // 2.0)
print(7.5 % 2.0)
print(2.0 ** 10.0)

# Unary
print(-3.14)
print(+3.14)
print(abs(-2.5))
print(abs(2.5))

# Comparisons
print(1.5 < 2.5)
print(2.5 < 1.5)
print(1.5 <= 1.5)
print(1.5 >= 1.5)
print(1.5 == 1.5)
print(1.5 != 2.5)

# Int-float mixed operations
print(3 + 1.5)
print(10 - 2.5)
print(3 * 2.5)
print(7 / 2)
print(7 // 2.0)

# Conversion
print(float(42))
print(float(-3))
print(float("3.14"))
print(float("-2.5"))
print(int(3.7))
print(int(-3.7))
print(int(3.0))

# Round
print(round(3.14159, 2))
print(round(3.14159, 4))
print(round(2.5))
print(round(3.5))
print(round(4.5))
print(round(-0.5))
print(round(1.5))

# Special values
print(float("inf") > 1000000)
print(float("-inf") < -1000000)

# Floor division edge cases
print(3.0 // 2.0)
print(-3.0 // 2.0)
print(3.0 // -2.0)
print(-3.0 // -2.0)

# Modulo edge cases
print(3.0 % 2.0)
print(-3.0 % 2.0)
print(3.0 % -2.0)

# Power
print(2.0 ** 0.5)
print(4.0 ** 0.5)
print(9.0 ** 0.5)
print(2.0 ** -1)

# Comparison with int
print(1.0 == 1)
print(2.0 == 2)
print(1.5 == 1)
print(0.0 == 0)

# String formatting
print(str(1.0))
print(str(0.5))
print(str(-3.14))
print(str(1000000.0))

# Min/max
print(min(1.5, 2.5, 0.5))
print(max(1.5, 2.5, 0.5))
