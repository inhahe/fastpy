# Regression: ZeroDivisionError message for int / 0 should say
# "division by zero" (CPython's exact message), not "float division by
# zero" — CPython only uses the latter when a float operand is involved.

try:
    x = 1 / 0
except ZeroDivisionError as e:
    print("caught:", e)

try:
    x = 1.0 / 0.0
except ZeroDivisionError as e:
    print("caught:", e)
