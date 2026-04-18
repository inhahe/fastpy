a = [1, 2, 3, 4, 5]
b = a[:]
b.append(99)
print(a)
print(b)

c = a[1:4]
c.append(88)
print(c)

d = ["x", "y", "z"]
e = d[:]
e.append("w")
print(e)
