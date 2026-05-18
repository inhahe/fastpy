# Adapted from CPython Lib/test/test_scope.py
# Tests variable scoping (local, enclosing, global)

# Global scope
x = 10
def read_global():
    return x
print(read_global())

# Local scope shadows global
y = 20
def local_shadow():
    y = 99
    return y
print(local_shadow())
print(y)  # global unchanged

# Nested function (closure)
def outer():
    n = 42
    def inner():
        return n
    return inner()
print(outer())

# Closure captures variable
def make_adder(n):
    def add(x):
        return x + n
    return add

add5 = make_adder(5)
add10 = make_adder(10)
print(add5(3))
print(add10(3))
print(add5(add10(0)))

# Multiple closures over same variable
def make_pair():
    val = [0]
    def getter():
        return val[0]
    def setter(x):
        val[0] = x
    return getter, setter

get, set_ = make_pair()
print(get())
set_(42)
print(get())
set_(100)
print(get())

# Closure in loop (with default arg capture)
funcs = []
for i in range(5):
    def f(x, i=i):
        return x + i
    funcs.append(f)

results = []
for fn in funcs:
    results.append(fn(10))
print(results)

# Nested closures (2 levels)
def level1(a):
    def level2(b):
        return a + b
    return level2

f = level1(10)
print(f(5))
print(f(20))

# Global declaration
counter = 0
def increment():
    global counter
    counter += 1
    return counter

print(increment())
print(increment())
print(increment())
print(counter)

# Variable in different scopes
def scope_test():
    x = "local"
    def inner():
        return x
    return inner()

x = "global"
print(scope_test())
print(x)

# Function arguments are local
def modify_arg(lst):
    lst = [99, 98, 97]  # rebind, doesn't affect caller
    return lst

original = [1, 2, 3]
result = modify_arg(original)
print(original)
print(result)

# But mutation is visible
def mutate_arg(lst):
    lst.append(99)

data = [1, 2, 3]
mutate_arg(data)
print(data)

# Conditional scope
def conditional_var(flag):
    if flag:
        result = "yes"
    else:
        result = "no"
    return result

print(conditional_var(True))
print(conditional_var(False))

# Loop variable scope (survives loop)
def loop_var():
    for i in range(5):
        pass
    return i

print(loop_var())

# Comprehension scope (doesn't leak in Python 3)
result = [x * 2 for x in range(5)]
# x from comprehension doesn't leak
print(result)
