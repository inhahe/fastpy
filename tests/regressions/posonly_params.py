# Regression test for positional-only parameters (PEP 570)

def add(a, b, /):
    return a + b

print(add(3, 4))        # 7

def greet(name, /, greeting="Hello"):
    return greeting + " " + name

print(greet("Alice"))                # Hello Alice
print(greet("Bob", "Hi"))            # Hi Bob

def mixed(x, /, y, *, z):
    return x + y + z

print(mixed(1, 2, z=3))  # 6

# Positional-only with default
def clamp(val, /, lo=0, hi=100):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val

print(clamp(50))         # 50
print(clamp(-5))         # 0
print(clamp(200))        # 100
