# Nonlocal closure tests: mutable captures, nested closures, cell sharing

# Basic nonlocal
def outer():
    x = 10
    def inner():
        nonlocal x
        x = 20
    inner()
    return x
assert outer() == 20
print("basic ok")

# Counter pattern (returned closure)
def make_counter():
    count = 0
    def increment():
        nonlocal count
        count += 1
        return count
    return increment

c = make_counter()
assert c() == 1
assert c() == 2
assert c() == 3
print("counter ok")

# Multiple closures sharing the same nonlocal
def make():
    val = 0
    def inc():
        nonlocal val
        val += 1
    def get():
        nonlocal val
        return val
    inc()
    inc()
    inc()
    return get()
assert make() == 3
print("shared ok")

# Nested nonlocal (3 levels deep): h modifies f's variable through g
def f():
    x = 0
    def g():
        nonlocal x
        def h():
            nonlocal x
            x = 99
        h()
    g()
    return x
assert f() == 99
print("nested ok")

# Nonlocal with multiple variables
def multi():
    a = 1
    b = 2
    def swap():
        nonlocal a, b
        a, b = b, a
    swap()
    return (a, b)
assert multi() == (2, 1)
print("multi ok")

# Nonlocal in loop
def accumulator():
    total = 0
    def add(n):
        nonlocal total
        total += n
        return total
    return add
acc = accumulator()
for i in range(1, 6):
    r = acc(i)
assert r == 15  # 1+2+3+4+5
print("loop ok")
