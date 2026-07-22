# Adapted from CPython Lib/test/test_int.py
# Tests integer operations

# Basic arithmetic
print(2 + 3)
print(10 - 4)
print(3 * 7)
print(15 // 4)
print(15 % 4)
print(2 ** 10)
print(-7 // 2)
print(-7 % 2)
print(7 // -2)
print(7 % -2)

# Unary
print(-5)
print(+5)
print(abs(-42))
print(abs(42))

# Comparisons
print(3 < 5)
print(5 < 3)
print(3 <= 3)
print(3 >= 3)
print(3 == 3)
print(3 != 4)

# Bitwise operations
print(0b1010 & 0b1100)
print(0b1010 | 0b1100)
print(0b1010 ^ 0b1100)
print(~0)
print(~1)
print(1 << 4)
print(16 >> 2)
print(255 & 0xF0)
print(0x0F | 0xF0)

# Division
print(10 / 2)
print(7 / 2)
print(-7 / 2)
print(1 / 3)

# Large numbers
print(2 ** 30)
print(2 ** 31 - 1)
print(-(2 ** 31))
print(1000000 * 1000000)

# Conversion
print(int(3.7))
print(int(-3.7))
print(int("42"))
print(int("-17"))
print(int("ff", 16))
print(int("77", 8))
print(int("1010", 2))

# Bool as int
print(True + True)
print(True * 5)
print(False + 1)
print(int(True))
print(int(False))

# Divmod
print(divmod(17, 5))
print(divmod(-17, 5))
print(divmod(17, -5))
print(divmod(10, 2))

# Power with modulus
print(pow(2, 10, 1000))
print(pow(3, 7, 100))

# Min/max
print(min(3, 1, 4, 1, 5))
print(max(3, 1, 4, 1, 5))
print(min([2, 7, 1, 8]))
print(max([2, 7, 1, 8]))

# Integer identity
print(0 == False)
print(1 == True)
print(0 is not None)

# Chained comparisons
x = 5
print(1 < x < 10)
print(1 < x < 3)
print(0 <= x <= 5)
print(5 <= x <= 5)
