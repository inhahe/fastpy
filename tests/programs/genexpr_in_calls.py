# Generator expressions used inside function calls

# sum with genexpr
print(sum(x * x for x in range(10)))

# min / max with genexpr
words = ["apple", "hi", "banana", "ok"]
print(max(len(w) for w in words))
print(min(len(w) for w in words))

# any / all
nums = [2, 4, 6, 8, 10]
print(any(x > 9 for x in nums))
print(all(x % 2 == 0 for x in nums))
print(any(x < 0 for x in nums))

# sorted with key using lambda (related pattern)
pairs = [(2, "b"), (1, "a"), (3, "c")]
print(sorted(pairs, key=lambda p: p[0]))

# Nested genexpr
matrix = [[1, 2], [3, 4], [5, 6]]
flat = list(x for row in matrix for x in row)
print(flat)

# join with genexpr
result = ", ".join(str(x) for x in range(5))
print(result)

# tuple() from genexpr
t = tuple(x ** 2 for x in range(5))
print(t)

print("tests passed!")
