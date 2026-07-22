# Regression: sorted(dict, key=lambda w: dict[w])
# Previously crashed because:
# 1. Dict was passed directly to sorted_by_key without extracting keys
# 2. Lambda parameter was typed as INT instead of STR
# 3. Captured dict variable wasn't accessible from inline lambda

freq = {"apple": 3, "banana": 1, "cherry": 2}

# Sort by value ascending
words = sorted(freq, key=lambda w: freq[w])
print(words)

# Sort by value descending
words2 = sorted(freq, key=lambda w: freq[w], reverse=True)
print(words2)

# Sort by key length
words3 = sorted(freq, key=lambda w: len(w))
print(words3)
