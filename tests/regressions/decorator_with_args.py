"""Test decorator-with-arguments pattern (triple-nested closures)."""

def repeat(n):
    def decorator(fn):
        def wrapper(x):
            return fn(x) * n
        return wrapper
    return decorator

@repeat(3)
def double(x):
    return x * 2

print(double(5))  # (5*2)*3 = 30

@repeat(2)
def add_ten(x):
    return x + 10

print(add_ten(5))  # (5+10)*2 = 30

# Non-decorator usage of the same pattern
tripler = repeat(3)
my_func = tripler(lambda x: x + 1)
print(my_func(10))  # (10+1)*3 = 33

print("decorator with args tests passed!")
