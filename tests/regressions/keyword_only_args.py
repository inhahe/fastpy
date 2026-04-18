# Regression: keyword-only arguments (def f(a, *, b): ...)
#
# Before fix: _declare_user_function only scanned node.args.args, missing
# kwonlyargs. The keyword resolver in _emit_user_call also missed them,
# raising "unexpected keyword argument". _detect_string_params didn't
# check kw_defaults, so string-defaulted kwonly params weren't typed.

# Basic keyword-only
def f(a, *, b):
    return a + b

print(f(1, b=2))
print(f(10, b=20))

# Multiple kwonly
def g(a, *, b, c):
    return a + b + c

print(g(1, b=2, c=3))
print(g(10, c=30, b=20))  # order-independent

# Kwonly with defaults (string)
def greet(name, *, prefix="Hi", suffix="!"):
    return prefix + " " + name + suffix

print(greet("Alice"))
print(greet("Bob", prefix="Hello"))
print(greet("Carol", suffix="?"))
print(greet("Dave", prefix="Hey", suffix="!!"))

# Kwonly default with positional default (int-only values)
def config(name, timeout=30, *, retries=3):
    return name + ":" + str(timeout) + ":" + str(retries)

print(config("task1"))
print(config("task2", 60))
print(config("task3", retries=5))
print(config("task4", 60, retries=10))

# Bool defaults (positional and kwonly)
def fetch(url, cache=True, *, verbose=False):
    return url + "," + str(cache) + "," + str(verbose)

print(fetch("a"))
print(fetch("b", False))
print(fetch("c", verbose=True))
print(fetch("d", False, verbose=True))
