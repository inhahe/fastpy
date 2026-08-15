d = {}
i = 0
while i < 1000:
    d[i] = i * i
    i = i + 1
total = 0
j = 0
while j < 1000:
    i = 0
    while i < 1000:
        total = total + d[i]
        i = i + 1
    j = j + 1
print(total)
