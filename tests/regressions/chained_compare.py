# Chained comparisons

x = 5
print(1 < x < 10)    # True
print(1 < x < 4)     # False
print(10 > x > 1)    # True

a, b, c = 1, 2, 3
print(a <= b <= c)   # True
print(a <= b <= b)   # True
print(a < b > c)     # False
print(a < b < c)     # True

# With equality
print(1 == 1 == 1)   # True
print(1 == 1 == 2)   # False

# Ensure middle is only evaluated once
def f():
    print("called")
    return 5

print(1 < f() < 10)  # prints "called" once, then True

# Chained with not equal
print(1 != 2 != 3)   # True
print(1 != 1 != 2)   # False

# Three-way with mixed ops
print(1 <= 2 >= 1)   # True
print(0 < 1 <= 1 < 2)  # True
