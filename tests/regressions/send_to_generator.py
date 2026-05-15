# Regression: generator send() and yield-as-expression.
# Before fix:
# 1. _no_send flag persisted across calls (set in __next__, not cleared
#    before send()'s state switch, so send(5) saw stale flag → assigned None)
# 2. Conditional `self._x = None` in no-send branch triggered Rule 1 in
#    _class_obj_attrs, causing _emit_attr_load to return i8* pointer for
#    integer attributes → arithmetic crash
# 3. next(gen) as bare statement bypassed _emit_builtin_next (no builtin
#    dispatch in _emit_call), fell through to CPython bridge

# 1. Basic send — bare yield
def gen1():
    x = yield
    yield x * 2

c = gen1()
next(c)
print(c.send(5))

# 2. Send with initial yield value
def gen2():
    x = yield 0
    yield x * 2

c2 = gen2()
v1 = next(c2)
print("v1:", v1)
v2 = c2.send(5)
print("v2:", v2)

# 3. Send with print inside generator
def gen3():
    x = yield 0
    print("got", x)
    yield x * 2

c3 = gen3()
v1 = next(c3)
print("v1:", v1)
v2 = c3.send(5)
print("v2:", v2)

# 4. Multiple sends
def gen4():
    x = yield 0
    y = yield x + 1
    yield x + y

c4 = gen4()
print(next(c4))
print(c4.send(10))
print(c4.send(20))

# 5. Send zero (tests that 0 is passed correctly, not confused with None)
def gen5():
    x = yield 1
    yield x + 10

c5 = gen5()
print(next(c5))
print(c5.send(0))

# 6. Send with computation in generator
def gen6():
    x = yield 0
    r = x * 2
    print("r is", r)
    yield r

c6 = gen6()
v = next(c6)
print("first:", v)
v = c6.send(7)
print("second:", v)

# 7. next() as bare statement (was going through CPython bridge)
def gen7():
    yield 100
    yield 200

g7 = gen7()
next(g7)
print(next(g7))

# 8. Multiple generators interleaved
def gen8():
    x = yield
    yield x + 1

a = gen8()
b = gen8()
next(a)
next(b)
print(a.send(10))
print(b.send(20))

# 9. Send to generator used in loop
def gen9():
    total = 0
    while True:
        x = yield total
        if x is None:
            break
        total = total + x

g9 = gen9()
next(g9)
print(g9.send(1))
print(g9.send(2))
print(g9.send(3))

# 10. yield as expression in conditional
def gen10():
    x = yield 0
    if x > 0:
        yield x
    else:
        yield -x

c10 = gen10()
next(c10)
print(c10.send(5))

c10b = gen10()
next(c10b)
print(c10b.send(-3))
