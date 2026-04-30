"""Test try/except inside for loops and nested try/except."""

# Basic try/except in loop — no exception raised
total = 0
for i in range(5):
    try:
        total += i
    except:
        pass
print(total)  # 10

# try/except in loop with exception (division raises, append in except)
results = []
for x in [1, 0, 2, 0, 3]:
    try:
        results.append(10 // x)
    except:
        results.append(-1)
print(results)  # [10, -1, 5, -1, 3]

# Expression-only statement that raises inside try
try:
    a = 1
    b = 0
    a / b
except ZeroDivisionError:
    print("caught bare expr")

# Nested try/except with re-raise
try:
    try:
        1 // 0
    except ZeroDivisionError:
        print("inner caught")
        raise ValueError("re-raised")
except ValueError as e:
    print(f"outer: {e}")

# try/except with modulo by zero
try:
    x = 10 % 0
except ZeroDivisionError:
    print("mod by zero caught")

print("try in loop tests passed!")
