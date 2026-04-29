"""Test real-world Python patterns that users commonly write."""

# 1. f-string with expressions
name = "World"
x = 42
msg = f"Hello {name}, x={x}"
print(msg)

# 2. Multiple assignment
a, b, c = 1, 2, 3
print(a + b + c)  # 6

# 3. Ternary expression
val = 10
result = "big" if val > 5 else "small"
print(result)  # big

# 4. List comprehension with condition
nums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
evens = [n for n in nums if n % 2 == 0]
print(len(evens))  # 5

# 5. Dict comprehension
squares = {i: i*i for i in range(5)}
print(squares[4])  # 16

# 6. String methods chain
text = "  Hello, World!  "
clean = text.strip().lower()
print(clean)  # hello, world!

# 7. enumerate
words = ["foo", "bar", "baz"]
for i, w in enumerate(words):
    if i == 1:
        print(w)  # bar

# 8. zip
keys = ["a", "b", "c"]
vals = [1, 2, 3]
pairs = list(zip(keys, vals))
print(len(pairs))  # 3

# 9. any/all
print(any([False, False, True]))  # True
print(all([True, True, True]))    # True

# 10. try/except
try:
    x = 10 / 0
except:
    print("caught")  # caught

print("real patterns passed!")
