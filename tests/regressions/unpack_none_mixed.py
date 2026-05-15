# Regression: unpacking lists containing None or mixed types lost runtime
# type tags.  None was printed as 0, because the compile-time element type
# defaulted to INT and bare extraction discarded the NONE tag.

# 1. Literal list with None
x = [None]
a, = x
print(a)

# 2. Function returning list with None
def get_pair():
    r = []
    r.append(1)
    r.append(None)
    return r

a, b = get_pair()
print(a)
print(b)

# 3. Starred unpack with None at end
def get_mixed():
    r = []
    r.append(10)
    r.append("two")
    r.append(3.0)
    r.append(None)
    return r

first, *mid, last = get_mixed()
print(first)
print(mid)
print(last)

# 4. Heterogeneous return from function
def info():
    return ["hello", 42, 3.14, True, None]
s, i, f, b, n = info()
print(s)
print(i)
print(f)
print(b)
print(n)

# 5. Method returning mixed list
class Box:
    def contents(self):
        x = []
        x.append(None)
        x.append("text")
        return x

bx = Box()
n, t = bx.contents()
print(n)
print(t)
