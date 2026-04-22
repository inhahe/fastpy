# Regression tests for implemented-but-untested grammar features
# (Tests only features that are known to work correctly)

# ── Bytes literals ─────────────────────────────────────────────────
b = b"hello"
print(b)           # b'hello'
print(type(b))     # <class 'bytes'>

# ── for/else ───────────────────────────────────────────────────────
# else runs when loop completes without break
result = ""
for i in range(5):
    if i == 99:
        break
else:
    result = "completed"
print(result)  # completed

# else does NOT run when loop breaks
result2 = ""
for i in range(5):
    if i == 3:
        break
else:
    result2 = "completed"
print(result2)  # (empty string)

# ── while/else ─────────────────────────────────────────────────────
n = 0
result3 = ""
while n < 5:
    n += 1
else:
    result3 = "done"
print(result3)  # done

n = 0
result4 = ""
while n < 5:
    n += 1
    if n == 3:
        break
else:
    result4 = "done"
print(result4)  # (empty string)
