# Probe: word frequency counter with sorted iteration

def word_freq(text):
    words = text.split()
    freq = {}
    for w in words:
        if w not in freq:
            freq[w] = 0
        freq[w] += 1
    return freq

text = "the cat sat on the mat"
f = word_freq(text)
print(f)
for word in sorted(f.keys()):
    print(f"{word}: {f[word]}")
