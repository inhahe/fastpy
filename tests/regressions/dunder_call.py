"""Regression test: __call__ dunder method on user classes.

Previously, calling an object with __call__ (e.g., f()) would crash
because the expression-level dispatch routed VKind.OBJ to the
closure-call path (treating the object pointer as a function pointer).
Fixed by checking for __call__ before the closure-call fallback in
_emit_call_expr.
"""


# Test 1: basic no-arg __call__
class F:
    def __call__(self):
        print(42)

f = F()
f()

# Test 2: __call__ with args
class Adder:
    def __init__(self, n):
        self.n = n
    def __call__(self, x):
        return x + self.n

add5 = Adder(5)
print(add5(10))
print(add5(20))

# Test 3: __call__ with multiple args
class Mul:
    def __call__(self, a, b):
        return a * b

m = Mul()
print(m(3, 7))

# Test 4: __call__ result used in expression
class Inc:
    def __init__(self, n):
        self.n = n
    def __call__(self, x):
        return x + self.n

inc = Inc(10)
result = inc(5) + inc(3)
print(result)

# Test 5: __call__ returning string
class Greeter:
    def __init__(self, name):
        self.name = name
    def __call__(self):
        return "Hello " + self.name

g = Greeter("World")
print(g())

# Test 6: __call__ with inherited __init__
class Base:
    def __init__(self, x):
        self.x = x

class Callable(Base):
    def __call__(self):
        return self.x * 2

c = Callable(21)
print(c())

# Test 7: statement-level __call__ (void return)
class Logger:
    def __init__(self):
        self.count = 0
    def __call__(self, msg):
        self.count = self.count + 1
        print(msg)

log = Logger()
log("hello")
log("world")
print(log.count)

# Test 8: __call__ chaining (call-on-call)
class Counter:
    def __init__(self):
        self.n = 0
    def __call__(self):
        self.n = self.n + 1
        return self

ctr = Counter()
ctr()()()
print(ctr.n)

# Test 9: inline constructor __call__: C()(5)
class Doubler:
    def __call__(self, x):
        return x * 2

print(Doubler()(7))

# Test 10: len() on object with __len__
class Sized:
    def __len__(self):
        return 42

print(len(Sized()))
s = Sized()
print(len(s))
