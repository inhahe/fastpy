# Basic arithmetic test program
# Tests integer and float operations, operator precedence, big ints

print(1 + 2)
print(10 - 3)
print(6 * 7)
print(17 // 3)
print(17 % 3)
print(2 ** 10)
print(-42)
print(abs(-5))

# Float
print(1.5 + 2.5)
print(10.0 / 3.0)

# Mixed
print(1 + 2.5)
print(3 * 1.5)

# Precedence
print(2 + 3 * 4)
print((2 + 3) * 4)

# Big int (must work — Python semantics)
print(2 ** 100)
print(10 ** 20 + 1)

# Negative division
print(-7 // 2)
print(7 // -2)
print(-7 % 2)

# Chained comparison used in arithmetic context
print(int(1 < 2 < 3))
print(int(3 < 2 < 1))
