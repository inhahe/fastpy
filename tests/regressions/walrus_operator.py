# Test walrus operator := in while loops and if statements

# while loop: read until sentinel
data = [1, 2, 3, 4, 0, 5]
idx = 0
results = []
while (val := data[idx]) != 0:
    results.append(val)
    idx += 1
print(results)   # [1, 2, 3, 4]

# if statement
def first_even(lst):
    for x in lst:
        if (r := x % 2) == 0:
            return x
    return -1

print(first_even([1, 3, 5, 4, 6]))  # 4
print(first_even([1, 3, 5]))        # -1

# walrus in while with string processing
tokens = ["hello", "world", "", "done"]
out = []
i = 0
while (tok := tokens[i]) != "":
    out.append(tok.upper())
    i += 1
print(out)   # ['HELLO', 'WORLD']

# walrus capturing a function result
def compute(n):
    return n * n

values = []
n = 1
while (sq := compute(n)) < 50:
    values.append(sq)
    n += 1
print(values)   # [1, 4, 9, 16, 25, 36, 49]

# walrus in list comprehension condition
nums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
evens_doubled = [y for x in nums if (y := x * 2) > 8]
print(evens_doubled)   # [10, 12, 14, 16, 18, 20]
