# Test list.sort(reverse=True), list.sort(key=...), list.copy(), list.clear(),
# list.count(), list.index()

# sort reverse
a = [3, 1, 4, 1, 5, 9, 2, 6]
a.sort(reverse=True)
print(a)   # [9, 6, 5, 4, 3, 2, 1, 1]

# sort with key
b = ["banana", "apple", "cherry", "date"]
b.sort(key=lambda x: len(x))
print(b)   # ['date', 'apple', 'banana', 'cherry']

# sort with key and reverse
c = [3, 1, 4, 1, 5, 9]
c.sort(key=lambda x: -x)
print(c)   # [9, 5, 4, 3, 1, 1]

# list.copy()
orig = [1, 2, 3]
cp = orig.copy()
cp.append(4)
print(orig)  # [1, 2, 3]
print(cp)    # [1, 2, 3, 4]

# list.clear()
d = [10, 20, 30]
d.clear()
print(d)     # []

# list.count()
e = [1, 2, 2, 3, 2, 4]
print(e.count(2))   # 3
print(e.count(5))   # 0
print(e.count(1))   # 1

# list.index()
f = [10, 20, 30, 20, 40]
print(f.index(20))      # 1
print(f.index(20, 2))   # 3  (start from index 2)
print(f.index(40))      # 4
