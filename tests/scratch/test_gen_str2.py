# Minimal: string iter in generator
def chars(s):
    for c in s:
        yield c
g = chars("hi")
print(next(g))
