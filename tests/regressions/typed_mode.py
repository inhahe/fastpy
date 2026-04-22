# Regression test for --typed mode (annotation-driven fast paths)
# compile_flags: --typed

def add_ints(a: int, b: int) -> int:
    return a + b

def add_floats(x: float, y: float) -> float:
    return x + y

def mixed_ops(a: int, b: int) -> float:
    return a / b

def int_arithmetic(x: int, y: int) -> int:
    s = x + y
    d = x - y
    p = x * y
    return s + d + p

def float_arithmetic(x: float, y: float) -> float:
    s = x + y
    d = x - y
    p = x * y
    return s + d + p

def annotated_locals() -> int:
    x: int = 10
    y: int = 20
    z: int = x + y
    return z

def annotated_float_locals() -> float:
    a: float = 1.5
    b: float = 2.5
    return a * b

def loop_sum(n: int) -> int:
    total: int = 0
    i: int = 0
    while i < n:
        total = total + i
        i = i + 1
    return total

def compare_ints(a: int, b: int) -> bool:
    return a < b

# Test basic integer operations
print(add_ints(3, 4))       # 7
print(add_ints(100, -50))   # 50

# Test float operations
print(add_floats(1.5, 2.5))  # 4.0
print(add_floats(-1.0, 1.0)) # 0.0

# Test mixed (int / int returns float)
print(mixed_ops(10, 3))  # 3.3333333333333335

# Test int arithmetic combinations
print(int_arithmetic(5, 3))  # (5+3) + (5-3) + (5*3) = 8 + 2 + 15 = 25

# Test float arithmetic
print(float_arithmetic(2.0, 3.0))  # (2+3) + (2-3) + (2*3) = 5 + -1 + 6 = 10.0

# Test annotated local variables
print(annotated_locals())  # 30

# Test annotated float locals
print(annotated_float_locals())  # 3.75

# Test loop with typed accumulator
print(loop_sum(10))  # 45

# Test comparison
print(compare_ints(3, 5))  # True
print(compare_ints(5, 3))  # False

# Test unannotated code works normally alongside typed
def untyped_add(a, b):
    return a + b

print(untyped_add(10, 20))  # 30
