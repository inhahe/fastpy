# Regression: invalid binop combinations raise TypeError instead of crashing
# Tests that list+int, dict+int, etc. raise TypeError like CPython.

# list + int should raise TypeError
try:
    result = [1, 2, 3] + 5
    print("FAIL: list + int did not raise")
except TypeError as e:
    print("OK: list + int raised TypeError")

# list - list should raise TypeError
try:
    result = [1, 2] - [3]
    print("FAIL: list - list did not raise")
except TypeError as e:
    print("OK: list - list raised TypeError")

# dict + int should raise TypeError
try:
    d = {"a": 1}
    result = d + 1
    print("FAIL: dict + int did not raise")
except TypeError as e:
    print("OK: dict + int raised TypeError")

# Valid operations should still work
print([1, 2] + [3, 4])      # [1, 2, 3, 4]
print([1, 2] * 2)            # [1, 2, 1, 2]
print("ab" + "cd")           # abcd
print("ab" * 3)              # ababab
