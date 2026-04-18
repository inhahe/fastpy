# Exception handling patterns (simpler)

# Basic try/except
try:
    x = 1 / 0
except ZeroDivisionError as e:
    print("caught zdiv:", e)

# try/except/finally
def with_finally():
    try:
        return "tried"
    finally:
        print("finally ran")

print(with_finally())

# raise
def check(x):
    if x < 0:
        raise ValueError("negative not allowed")
    return x * 2

try:
    check(-5)
except ValueError as e:
    print("caught:", e)
print(check(5))
