def is_positive(x):
    return x > 0

def is_even(n):
    return n % 2 == 0

def int_equal(a, b):
    return a == b

def not_op(x):
    return not x

print(is_positive(5))
print(is_positive(-3))
print(is_even(4))
print(is_even(7))
print(int_equal(1, 1))
print(int_equal(1, 2))
print(not_op(True))
print(not_op(False))

# Use bool result in conditionals
if is_positive(10):
    print("ten is positive")
if not is_even(3):
    print("three is odd")
