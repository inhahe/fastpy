# Module-level exceptions should halt execution immediately
# Bug #111: fv_binop raises TypeError but execution continues

# Case 1: list + int should raise TypeError
import sys

# Test that exception halts execution
try:
    exec("x = []; x + 0")
except TypeError:
    print("caught TypeError")

# Case 2: Various module-level error patterns that should halt
def test_div_zero():
    try:
        result = 1 / 0
    except ZeroDivisionError:
        print("caught div zero")

test_div_zero()

# Case 3: Operation that succeeds (should not be affected)
a = [1, 2, 3]
b = [4, 5, 6]
print(a + b)

# Case 4: String * negative (should return empty)
print("abc" * -1)

# Case 5: Valid operations after error handling
d = {"a": 1}
print(d.get("b", "missing"))
