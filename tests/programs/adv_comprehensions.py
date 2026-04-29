# Advanced comprehensions: nested, set comp, conditional, dict comp from lists

# nested list comp — flatten matrix
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
flat = [x for row in matrix for x in row]
print(flat)

# conditional nested comprehension
evens = [x for row in matrix for x in row if x % 2 == 0]
print(evens)

# set comprehension
words = ["hello", "world", "hello", "foo", "world"]
unique_lengths = sorted({len(w) for w in words})
print(unique_lengths)

# dict comprehension from two lists
keys = ["a", "b", "c", "d"]
vals = [1, 2, 3, 4]
d = {k: v for k, v in zip(keys, vals) if v > 1}
print(sorted(d.items()))

# nested comprehension producing list of lists
mul_table = [[i * j for j in range(1, 4)] for i in range(1, 4)]
for row in mul_table:
    print(row)

# comprehension with ternary
labels = ["even" if x % 2 == 0 else "odd" for x in range(6)]
print(labels)

# generator expression in sum/min/max
total = sum(x * x for x in range(5))
print(f"sum_sq={total}")

biggest = max(len(w) for w in words)
print(f"max_len={biggest}")

print("tests passed!")
