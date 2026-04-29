# Regression: multiple decorator chaining
# @d1 @d2 def f means f = d1(d2(f)) — bottom-up application

def identity(f):
    return f

def double_result(fn):
    def wrapper(x):
        return fn(x) * 2
    return wrapper

def add_one(fn):
    def wrapper(x):
        return fn(x) + 1
    return wrapper

# 1. Two decorators: identity wrapping double_result
@identity
@double_result
def square(x):
    return x * x

print(square(3))   # 18  (9 * 2)
print(square(5))   # 50  (25 * 2)

# 2. Two functional decorators: add_one(double_result(cube))
@add_one
@double_result
def cube(x):
    return x * x * x

print(cube(2))   # 17  (8 * 2 + 1)
print(cube(3))   # 55  (27 * 2 + 1)

# 3. Manual chaining should match decorator syntax
def plain_sq(x):
    return x * x

manual = add_one(double_result(plain_sq))
print(manual(4))   # 33  (16 * 2 + 1)

# 4. Three decorators
@identity
@add_one
@double_result
def triple(x):
    return x + 1

print(triple(4))   # 11  ((4+1)*2 + 1 = 11)
print(triple(9))   # 21  ((9+1)*2 + 1 = 21)
