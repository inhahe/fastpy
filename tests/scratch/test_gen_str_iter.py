# Test: string iteration inside generator
def chars(s):
    for c in s:
        yield c

g = chars("abc")
print(next(g))
print(next(g))
print(next(g))
