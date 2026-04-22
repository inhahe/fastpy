# Regression test for --typed mode boundary cases
# compile_flags: --typed

# Test: typed function called from untyped context
def typed_add(a: int, b: int) -> int:
    return a + b

result = typed_add(3, 7)
print(result)  # 10

# Test: typed function with float, called with int (promotion)
def typed_float_fn(x: float, y: float) -> float:
    return x + y

print(typed_float_fn(1.0, 2.0))  # 3.0

# Test: annotated locals with reassignment
def reassign_test() -> int:
    x: int = 5
    x = x + 10
    x = x * 2
    return x

print(reassign_test())  # 30

# Test: typed function as inner expression
def combine(a: int, b: int) -> int:
    return a * 10 + b

print(combine(3, 7) + combine(1, 2))  # 37 + 12 = 49

# Test: while loop with typed counter
def countdown(n: int) -> int:
    count: int = 0
    while n > 0:
        count = count + 1
        n = n - 1
    return count

print(countdown(5))  # 5

# Test: if/else with typed variables
def abs_val(x: int) -> int:
    if x < 0:
        return -x
    return x

print(abs_val(-42))  # 42
print(abs_val(17))   # 17

# Test: bool annotation
def is_positive(x: int) -> bool:
    return x > 0

print(is_positive(5))   # True
print(is_positive(-3))  # False

# Test: string annotation
def greet(name: str) -> str:
    return "Hello, " + name + "!"

print(greet("World"))  # Hello, World!

# Test: multiple typed functions calling each other
def double(x: int) -> int:
    return x * 2

def quad(x: int) -> int:
    return double(double(x))

print(quad(3))  # 12

# Test: typed float accumulator in loop
def float_sum(n: int) -> float:
    total: float = 0.0
    i: int = 1
    while i <= n:
        total = total + 1.0 / i
        i = i + 1
    return total

# Harmonic number H(5) = 1 + 1/2 + 1/3 + 1/4 + 1/5
print(float_sum(5))  # 2.283333333333333
