# Adapted from CPython Lib/test/test_unary.py
# Tests unary operators

# Unary minus
print(-0)
print(-1)
print(-(-1))
print(-100)
print(-3.14)
print(-(-3.14))
print(-0.0)

# Unary plus
print(+0)
print(+1)
print(+(-1))
print(+3.14)

# Bitwise not
print(~0)
print(~1)
print(~(-1))
print(~255)
print(~(-256))
print(~0xFF)

# not operator
print(not True)
print(not False)
print(not 0)
print(not 1)
print(not "")
print(not "hello")
print(not [])
print(not [1])
print(not None)

# Combined with arithmetic
x = 5
print(-x)
print(-x + 10)
print(-(x + 10))
print(-x * 2)
print(-(x * 2))

# Double negation
y = -7
print(-y)
print(-(-y))
print(-(-(-y)))

# Unary in expressions
a = 3
b = 4
print(-a + b)
print(a + -b)
print(-a + -b)
print(-a - -b)

# Not in conditions
values = [0, 1, 2, "", "x", None, True, False, [], [1]]
for v in values:
    if not v:
        print("falsy")
    else:
        print("truthy")

# Bitwise not patterns
for i in range(8):
    print(~i, end=" ")
print()

# Abs (related to unary minus)
print(abs(5))
print(abs(-5))
print(abs(0))
print(abs(3.14))
print(abs(-3.14))
print(abs(0.0))
