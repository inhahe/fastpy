# More Python patterns to stress-test correctness

# f-strings with expressions
x = 10
y = 3.14
name = "World"
print(f"Hello, {name}!")
print(f"x = {x}, y = {y:.2f}")
print(f"{x + 5}")
print(f"{'upper' if x > 5 else 'lower'}")
print(f"{x:5d}")
print(f"{y:10.3f}")

# List methods
lst = [3, 1, 4, 1, 5, 9, 2, 6]
print(sorted(lst))
print(sorted(lst, reverse=True))
print(min(lst), max(lst))
print(sum(lst))
print(len(lst))
lst.sort()
print(lst)
lst.reverse()
print(lst)

# List comprehension variants
print([x*2 for x in range(5)])
print([x for x in range(10) if x % 2 == 0])
print({x: x*x for x in range(5)})
print(sorted({x % 3 for x in range(10)}))

# String methods
s = "  Hello, World!  "
print(s.strip())
print(s.strip().lower())
print(len(s.strip()))

# Numeric
print(abs(-5))
print(abs(-3.14))
print(round(3.7))
print(round(3.14159, 2))
print(pow(2, 10))
print(pow(2, 10, 1000))  # 2^10 mod 1000 = 24

# Assertion
assert 1 + 1 == 2
try:
    assert 1 + 1 == 3, "math broke"
except AssertionError as e:
    print("caught:", e)

# Chained comparisons
a = 5
print(1 < a < 10)   # True
print(1 < a > 10)   # False

# Enumerate + zip
names = ["alice", "bob", "charlie"]
ages = [30, 25, 35]
for i, (n, a) in enumerate(zip(names, ages)):
    print(i, n, a)

# Reversed
for x in reversed([1, 2, 3]):
    print(x)
