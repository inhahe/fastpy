# Regression: ZeroDivisionError message should always say "division by
# zero" to match CPython 3.14+ (which uses this message for all numeric
# types, including float).

try:
    x = 1 / 0
except ZeroDivisionError as e:
    print("caught:", e)

try:
    x = 1.0 / 0.0
except ZeroDivisionError as e:
    print("caught:", e)
