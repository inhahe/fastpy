# Regression: lexicographic comparison of tuples/lists.

t1 = (1, 2)
t2 = (1, 3)
print(t1 < t2)    # True
print(t1 <= t2)   # True
print(t2 > t1)    # True
print(t2 >= t1)   # True
print(t1 == t1)   # True
print(t1 != t2)   # True

# Mixed int/float
a = (1, 2.5)
b = (1, 3)
print(a < b)      # True

# Different lengths
c = (1, 2, 3)
d = (1, 2)
print(d < c)      # True (d is prefix of c)
print(c > d)      # True

# Lists too
l1 = [1, 2]
l2 = [1, 3]
print(l1 < l2)    # True
print(l1 <= l1)   # True
