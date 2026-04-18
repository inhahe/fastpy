# Miscellaneous Python patterns

# String slicing with steps
s = "abcdefgh"
print(s[::2])         # aceg
print(s[::-1])        # hgfedcba
print(s[1:6:2])       # bdf

# Multi-line string
x = """line1
line2
line3"""
print(x)
print(len(x))

# Enumerate
for i, v in enumerate(["a", "b", "c"]):
    print(i, v)

# Sum with generator-like
total = sum(range(10))
print(total)
total = sum(x*x for x in range(5))  # may not work — comprehension
print(total)

# max/min of string list
words = ["apple", "banana", "kiwi", "date"]
print(max(words))
print(min(words))

# dict.items() in for loop
d = {"a": 1, "b": 2, "c": 3}
for k, v in sorted(d.items()):
    print(k, "=", v)

# Comprehension with multi-var
pairs = [(i, j) for i in range(3) for j in range(2)]
print(pairs)

# Conditional in list comp
vals = [x if x > 5 else -x for x in range(10)]
print(vals)
