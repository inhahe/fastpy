"""Test closure default parameter values (integer defaults)."""

def outer(x=10):
    def inner(y=20):
        return x + y
    return inner

f = outer()
print(f())    # 30 (x=10, y=20)
print(f(5))   # 15 (x=10, y=5)

g = outer(100)
print(g())    # 120 (x=100, y=20)
print(g(1))   # 101 (x=100, y=1)

# Multiple defaults
def make_calc(base=0):
    def calc(x=1, y=2):
        return base + x * y
    return calc

c = make_calc(10)
print(c())       # 10 + 1*2 = 12
print(c(3))      # 10 + 3*2 = 16
print(c(3, 4))   # 10 + 3*4 = 22

print("closure defaults tests passed!")
