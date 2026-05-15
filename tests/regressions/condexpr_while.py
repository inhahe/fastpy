# Conditional expression in while loop

lst = [1, 2, 3]
i = 0
result = []
while i < len(lst):
    val = lst[i] if i < 3 else 0
    result.append(val)
    i += 1
assert result == [1, 2, 3], f"got {result}"
print("condexpr while ok")

# IfExp with None branch: val is None must work
val = 10 if True else None
assert val is not None
assert val == 10
print("ifexp not none ok")

val2 = 10 if False else None
assert val2 is None
print("ifexp is none ok")

# In a loop: None branch + is None check
i = 0
count = 0
while i < 3:
    val = i * 10 if i > 0 else None
    if val is not None:
        count += 1
    i += 1
assert count == 2, f"count={count}"
print("condexpr none loop ok")

# String branch vs None
s = "hello" if True else None
assert s is not None
assert s == "hello"
s2 = "hello" if False else None
assert s2 is None
print("condexpr str none ok")
