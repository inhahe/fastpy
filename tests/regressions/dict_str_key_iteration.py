# Regression: dict comprehension with str() keys and for-loop iteration
# Bug: for k in d: print(k, d[k]) fails with KeyError after first key
# when d is built from {str(i): value for i in range(n)}.

# Case 1: dict comprehension with str(i) keys
d1 = {str(i): i * i for i in range(5)}
for k in d1:
    print(k, d1[k])

# Case 2: dict literal with string keys (control — should work)
d2 = {"a": 1, "b": 2, "c": 3}
for k in d2:
    print(k, d2[k])
