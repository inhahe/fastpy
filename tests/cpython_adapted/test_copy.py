# Adapted from CPython Lib/test/test_copy.py
# Tests shallow and deep copy patterns

# Shallow copy of list
a = [1, 2, 3, 4, 5]
b = a.copy()
b.append(6)
print(a)
print(b)
print(a == b)

# Shallow copy shares nested objects
original = [[1, 2], [3, 4], [5, 6]]
shallow = []
for item in original:
    shallow.append(item)
shallow.append([7, 8])
print(len(original))
print(len(shallow))
# Mutation of shared nested list
original[0].append(99)
print(shallow[0])  # also has 99

# Deep copy of nested list
def deep_copy_list(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.append(deep_copy_list(item))
        else:
            result.append(item)
    return result

orig = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
deep = deep_copy_list(orig)
orig[0][0] = 99
print(orig[0])
print(deep[0])  # unchanged

# Dict copy
d1 = {"a": 1, "b": 2, "c": 3}
d2 = d1.copy()
d2["d"] = 4
print(sorted(d1.items()))
print(sorted(d2.items()))

# Deep copy of dict with lists
def deep_copy_dict(d):
    result = {}
    for k, v in d.items():
        if isinstance(v, list):
            result[k] = deep_copy_list(v)
        elif isinstance(v, dict):
            result[k] = deep_copy_dict(v)
        else:
            result[k] = v
    return result

d_orig = {"nums": [1, 2, 3], "name": "test"}
d_deep = deep_copy_dict(d_orig)
d_orig["nums"].append(4)
print(d_orig["nums"])
print(d_deep["nums"])  # unchanged

# Copy of class instances
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def copy(self):
        return Point(self.x, self.y)

p1 = Point(1, 2)
p2 = p1.copy()
p2.x = 99
print(p1.x, p1.y)
print(p2.x, p2.y)

# Copy of class with list attribute
class Container:
    def __init__(self, items):
        self.items = items

    def shallow_copy(self):
        return Container(self.items)

    def deep_copy(self):
        return Container(self.items.copy())

c1 = Container([1, 2, 3])
c2 = c1.shallow_copy()
c3 = c1.deep_copy()

c1.items.append(4)
print(c1.items)
print(c2.items)  # affected (shallow)
print(c3.items)  # not affected (deep)

# Copy preserves type
lst_copy = [1, 2, 3].copy()
print(type(lst_copy).__name__)
print(lst_copy)

# Slice copy
x = [10, 20, 30, 40, 50]
y = x[:]
x.append(60)
print(x)
print(y)

# Empty copies
print([].copy())
print({}.copy())
