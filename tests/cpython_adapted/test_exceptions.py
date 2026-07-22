# Adapted from CPython Lib/test/test_exceptions.py
# Tests exception handling

# Basic try/except
try:
    x = 1 / 0
except ZeroDivisionError:
    print("caught zero division")

# Catch with variable
try:
    y = int("not a number")
except ValueError as e:
    print("caught:", str(e))

# Multiple except clauses
def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return "division by zero"
    except TypeError:
        return "type error"

print(safe_divide(10, 2))
print(safe_divide(10, 0))

# Try/except/else
def divide(a, b):
    try:
        result = a / b
    except ZeroDivisionError:
        print("error: division by zero")
        return None
    else:
        print("success:", result)
        return result

divide(10, 2)
divide(10, 0)

# Try/except/finally
def with_finally(x):
    try:
        if x == 0:
            raise ValueError("zero!")
        return 100 // x
    except ValueError as e:
        print("error:", e)
        return -1
    finally:
        print("cleanup for", x)

print(with_finally(5))
print(with_finally(0))

# Nested try blocks
try:
    try:
        raise TypeError("inner")
    except TypeError as e:
        print("caught inner:", e)
        raise ValueError("outer")
except ValueError as e:
    print("caught outer:", e)

# Raise and re-raise
def might_fail(x):
    if x < 0:
        raise ValueError("negative: " + str(x))
    return x * 2

try:
    might_fail(-5)
except ValueError as e:
    print("got:", e)

# Exception in loop
errors = []
for val in [1, 0, 2, 0, 3]:
    try:
        errors.append(10 // val)
    except ZeroDivisionError:
        errors.append(-1)
print(errors)

# Custom exception classes
class AppError:
    def __init__(self, message, code=0):
        self.message = message
        self.code = code

    def __str__(self):
        return self.message + " (code " + str(self.code) + ")"

err = AppError("not found", 404)
print(err)

# Exception types
def check_type(value):
    try:
        if not isinstance(value, int):
            raise TypeError("expected int")
        if value < 0:
            raise ValueError("must be positive")
        return value
    except TypeError as e:
        return "TypeError: " + str(e)
    except ValueError as e:
        return "ValueError: " + str(e)

print(check_type(42))
print(check_type(-1))
print(check_type("hi"))

# Finally always runs
def always_cleanup():
    results = []
    try:
        results.append("try")
        return results
    finally:
        results.append("finally")

print(always_cleanup())

# Multiple exceptions in sequence
for i in range(5):
    try:
        if i == 1:
            raise ValueError("one")
        if i == 3:
            raise TypeError("three")
        print("ok:", i)
    except ValueError as e:
        print("val:", e)
    except TypeError as e:
        print("type:", e)
