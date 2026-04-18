words = "the quick brown fox the quick the".split()
counts = {}
for w in words:
    if w in counts:
        counts[w] += 1
    else:
        counts[w] = 1
for k in sorted(counts):
    print(k, counts[k])
