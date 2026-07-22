# Regression: closures accessing module-level global variables
# Bug: closure bodies were compiled during Pass 0.5 (scan phase),
# before _global_vars was populated (Pass 0.72). Any closure that
# referenced a module-level variable got NameError at runtime.

MULTIPLIER = 10

# 1. Real closure capturing a local AND reading a global
def make_func():
    offset = 5
    def inner(x):
        return x * MULTIPLIER + offset
    return inner

f = make_func()
print(f(3))   # 35  (3 * 10 + 5)
print(f(0))   # 5   (0 * 10 + 5)

# 2. Closure reading only globals (zero captures would be hoisted,
#    but if there's also a local capture, the global must still work)
BASE = 100
def make_adder():
    step = 1
    def add(x):
        return x + BASE + step
    return add

a = make_adder()
print(a(0))    # 101
print(a(50))   # 151

# 3. Inner function in class method reading a global
GREETING = "Hello"
class Greeter:
    def greet(self, name):
        def helper():
            return GREETING + " " + name
        return helper()

g = Greeter()
print(g.greet("World"))  # Hello World
