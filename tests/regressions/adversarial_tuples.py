# Tuple patterns

# Tuple unpacking
a, b = 1, 2
print(a, b)

# Swap
a, b = b, a
print(a, b)

# Function returning tuple
def divmod_custom(a, b):
    return a // b, a % b

q, r = divmod_custom(17, 5)
print(q, r)

# Tuple in list
pairs = [(1, 2), (3, 4)]
for p in pairs:
    print(p[0], p[1])

# Iterating over tuple variable (added after Phase 18)
nums = (10, 20, 30)
total = 0
for n in nums:
    total = total + n
print(total)

# Tuple lexicographic comparison (added after Phase 18)
t1 = (1, 2)
t2 = (1, 3)
print(t1 < t2)
print(t1 == t1)
