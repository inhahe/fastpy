# Regression: keyword-only params after *args

# Case 1: def f(*args, sep=", "):  — no positional params
def join_items(*args, sep=", "):
    result = ""
    for i, arg in enumerate(args):
        if i > 0:
            result = result + sep
        result = result + str(arg)
    return result

print(join_items(1, 2, 3))
print(join_items(1, 2, 3, sep=" - "))
print(join_items("a", "b", sep=":"))

# Case 2: positional + *rest + kwonly, integer first arg
def show_nums(first, *rest, end="."):
    result = str(first)
    for item in rest:
        result = result + " " + str(item)
    result = result + end
    return result

print(show_nums(1))
print(show_nums(1, 2, 3))
print(show_nums(1, 2, 3, end="!"))

# Case 3: kwonly with no positional, multiple kwonly params
def format_list(*items, sep=", ", prefix="[", suffix="]"):
    result = prefix
    for i, item in enumerate(items):
        if i > 0:
            result = result + sep
        result = result + str(item)
    result = result + suffix
    return result

print(format_list(1, 2, 3))
print(format_list(1, 2, 3, sep=" | "))
print(format_list(1, 2, 3, prefix="(", suffix=")"))

# Case 4: keyword-only int param
def repeat_args(*args, times=1):
    result = 0
    for arg in args:
        result = result + arg * times
    return result

print(repeat_args(1, 2, 3))
print(repeat_args(1, 2, 3, times=2))
