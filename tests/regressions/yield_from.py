# Regression: yield from produces wrong values.
# Before fix: yield from inner() returned 0 for first value because:
# 1. next() returns FpyValue struct but _emit_attr_store silently dropped it
#    (struct type didn't match IntType/PointerType/DoubleType tag detection)
# 2. send() method's return set_ret_tag used static inference (always INT)
#    instead of loading the runtime tag from the slot
# 3. __next__() overwrote the correct tag from send() with static INT tag

# 1. Basic yield from — int
def gen3():
    yield 1
    yield 2
    yield 3

def proxy():
    yield from gen3()

print(list(proxy()))

# 2. yield from — string
def greet():
    yield "hello"
    yield "world"

def greet_proxy():
    yield from greet()

print(list(greet_proxy()))

# 3. for-loop over yield-from string generator
for s in greet_proxy():
    print(s)

# 4. yield before and after yield-from
def outer():
    yield 0
    yield from gen3()
    yield 4

print(list(outer()))

# 5. Nested yield from
def mid():
    yield from gen3()

def top():
    yield from mid()

print(list(top()))

# 6. Multiple yield-from in sequence
def chain():
    yield from gen3()
    yield from gen3()

print(list(chain()))

# 7. Fibonacci via yield-from
def fib(n):
    a, b = 0, 1
    i = 0
    while i < n:
        yield a
        a, b = b, a + b
        i = i + 1

def fib_proxy(n):
    yield from fib(n)

print(list(fib_proxy(8)))

# 8. next() on yield-from generator
g = greet_proxy()
print(next(g))
print(next(g))

# 9. sum/len of yield-from result
nums = list(proxy())
print(sum(nums))
print(len(nums))

# 10. Comprehension over yield-from
print([x * 2 for x in proxy()])
