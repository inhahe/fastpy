# Error handling: try/except/finally, custom exceptions

class AppError(Exception):
    pass

# Raise and catch custom exception
try:
    raise AppError("something went wrong")
except AppError as e:
    print(f"caught: {e}")

# Nested try/except
try:
    try:
        raise ValueError("inner")
    except ValueError:
        print("inner caught")
        raise RuntimeError("outer")
except RuntimeError as e:
    print(f"outer caught: {e}")

# Multiple except types
def safe_div(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return float('inf')
    except TypeError:
        return -1

print(safe_div(10, 3))
print(safe_div(10, 0))

# finally
x = 0
try:
    x = 1
    raise ValueError("test")
except ValueError:
    x = 2
finally:
    x = x + 10
print(x)

print("tests passed!")
