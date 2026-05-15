# Regression: generator send() with None vs int values
# Bug: When both next() and send() are used, the _sent parameter's
# call_tag resolved to "int" from send(99), overriding the polymorphic
# FpyValue handling. This caused next() (which sends None) to deliver
# int(0) instead of None to the yield expression.

# 1. val = yield with next() should receive None
def gen1():
    while True:
        val = yield 42
        print(type(val).__name__, repr(val))

g = gen1()
next(g)       # prime
next(g)       # val should be None, not 0
g.send(99)    # val should be 99
g.send(None)  # val should be None

# 2. if val is not None check should work correctly
def gen2():
    while True:
        val = yield 42
        if val is not None:
            print("got:", val)
        else:
            print("got None")

g2 = gen2()
next(g2)
next(g2)       # should print "got None"
g2.send(99)    # should print "got: 99"

# 3. Stateful counter with send()
def counter(start):
    n = start
    while True:
        val = yield n
        if val is not None:
            n = val
        else:
            n += 1

g3 = counter(0)
print(next(g3))     # 0
print(next(g3))     # 1
print(g3.send(10))  # 10
print(next(g3))     # 11
