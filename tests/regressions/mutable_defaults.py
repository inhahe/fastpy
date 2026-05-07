# Mutable default arguments: Python evaluates defaults once at def-time,
# so list/dict/set defaults are shared across calls.

# Basic list default
def f(x, lst=[]):
    lst.append(x)
    return lst
r = f(1)
assert r == [1]
r = f(2)
assert r == [1, 2]
r = f(3)
assert r == [1, 2, 3]
print("list default ok")

# Dict default
def g(x, d={}):
    d[x] = x * 2
    return d
r = g(1)
assert 1 in r and r[1] == 2
r = g(2)
assert 1 in r and 2 in r
print("dict default ok")

# Multiple mutable defaults — verify via individual checks
def multi(a, b=[], c={}):
    b.append(a)
    c[a] = len(b)
    return b
r1 = multi(1)
assert r1 == [1]
r2 = multi(2)
assert r2 == [1, 2]
print("multi mutable ok")

# Mixed: immutable + mutable defaults
def mixed(x, y=10, lst=[]):
    lst.append(x + y)
    return lst
assert mixed(1) == [11]
assert mixed(2) == [11, 12]
assert mixed(3, y=100) == [11, 12, 103]
print("mixed defaults ok")

# Override default: providing explicit arg shouldn't affect cached default
def h(x, lst=[]):
    lst.append(x)
    return lst
assert h(1) == [1]
assert h(2, [100]) == [100, 2]  # uses provided list
assert h(3) == [1, 3]  # back to cached default
print("override ok")

# Two separate functions: each gets own cached default
def fa(x, lst=[]):
    lst.append(x)
    return lst
def fb(x, lst=[]):
    lst.append(x * 10)
    return lst
assert fa(1) == [1]
assert fb(1) == [10]
assert fa(2) == [1, 2]
assert fb(2) == [10, 20]
print("separate funcs ok")
