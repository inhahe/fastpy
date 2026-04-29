# Regression: type(e).__name__ and type(e) for caught exceptions

try:
    x = 1 / 0
except ZeroDivisionError as e:
    print(type(e).__name__)
    print(type(e))

try:
    d = {}
    v = d["missing"]
except KeyError as e:
    print(type(e).__name__)

try:
    lst = [1, 2, 3]
    v = lst[10]
except IndexError as e:
    print(type(e).__name__)

# Bare except (no class name)
try:
    raise ValueError("oops")
except ValueError as e:
    print(type(e).__name__)
    print(e)
