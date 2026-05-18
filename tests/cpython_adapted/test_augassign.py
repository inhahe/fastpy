# Adapted from CPython Lib/test/test_augassign.py
# Tests augmented assignment operators

# Integer +=, -=, *=, //=, %=, **=
x = 10
x += 5
print(x)
x -= 3
print(x)
x *= 2
print(x)
x //= 5
print(x)
x %= 3
print(x)
x **= 4
print(x)

# Float augmented ops
y = 3.0
y += 1.5
print(y)
y -= 0.5
print(y)
y *= 2.0
print(y)
y /= 4.0
print(y)

# Bitwise augmented ops
a = 0xFF
a &= 0x0F
print(a)
a |= 0x30
print(a)
a ^= 0x55
print(a)

b = 1
b <<= 4
print(b)
b >>= 2
print(b)

# String +=
s = "hello"
s += " "
s += "world"
print(s)

# String *=
t = "ab"
t *= 3
print(t)

# List +=
lst = [1, 2, 3]
lst += [4, 5]
print(lst)

# List *=
m = [1, 2]
m *= 3
print(m)

# Augmented assignment in loop
total = 0
for i in range(10):
    total += i
print(total)

product = 1
for i in range(1, 6):
    product *= i
print(product)

# Augmented on subscript
arr = [1, 2, 3, 4, 5]
arr[0] += 10
arr[2] *= 3
arr[-1] -= 1
print(arr)

# Augmented on attribute
class Counter:
    def __init__(self):
        self.value = 0

c = Counter()
c.value += 1
c.value += 1
c.value += 1
print(c.value)
c.value *= 5
print(c.value)
c.value -= 10
print(c.value)

# Mixed int/float augmented
z = 10
z += 0.5
print(z)
z *= 2
print(z)

# Augmented with negative
n = 100
n += -50
print(n)
n -= -25
print(n)
n *= -1
print(n)
