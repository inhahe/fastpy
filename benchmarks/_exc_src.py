d = {1: 10, 2: 20}
total = 0
i = 0
while i < 5:
    try:
        total = total + d[i]
    except KeyError as e:
        total = total + 100
        print("miss", e)
    i = i + 1
print("total", total)
def f(k):
    return d[k]
try:
    print(f(99))
except KeyError as e:
    print("caught from callee", e)
print("done")
