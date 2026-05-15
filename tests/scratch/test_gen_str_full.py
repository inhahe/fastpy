# Full test: string iteration in generator
def chars(s):
    for c in s:
        yield c

g = chars("hi")
print(next(g))
print(next(g))

# Also test list()
print(list(chars("abc")))
