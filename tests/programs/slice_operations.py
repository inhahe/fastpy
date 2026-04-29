# Slice operations: basic slicing, negative indices, slice assignment, step slicing

lst = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
print(lst[2:5])
print(lst[:3])
print(lst[7:])
print(lst[-3:])
print(lst[-5:-2])
print(lst[::2])
print(lst[1::2])
print(lst[::-1])
print(lst[8:2:-2])

# Slice assignment
a = [0, 1, 2, 3, 4, 5]
a[1:3] = [10, 20, 30]
print(a)

b = [0, 1, 2, 3, 4]
b[1:4] = []
print(b)

# Slice on strings (read-only)
s = "hello world"
print(s[0:5])
print(s[::-1])
print(s[6:])
print(s[-5:])

# Slice with None equivalent
t = (10, 20, 30, 40, 50)
print(t[1:4])
print(t[::-2])

print("tests passed!")
