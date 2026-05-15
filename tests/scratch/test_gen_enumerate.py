# Test: generator with enumerate-like pattern over string
def indexed_chars(s):
    i = 0
    for c in s:
        yield (i, c)
        i += 1

for pair in indexed_chars("abc"):
    print(pair)
