# Regression: ternary expressions with mixed-type branches
# Bug: when branches had different semantic types (e.g. int vs str,
# None variable vs str), the compiler normalized both to i64 and
# lost the runtime type tag. Result was printed as a raw integer
# (the ptrtoint'd string pointer) instead of the actual string.
# Fix: detect mixed-type branches at AST level and use fpy_val path
# (tag phi + data phi) to preserve runtime type information.

# Case 1: None variable vs string default
y = None
val = y if y is not None else "default"
print(val)

# Case 2: int vs string
flag = False
val2 = 42 if flag else "no"
print(val2)

# Case 3: None or default pattern
x = None
result = x if x is not None else "fallback"
print(result)

# Case 4: same type branches (should still work)
a = 5
val3 = "yes" if a > 3 else "no"
print(val3)

# Case 5: int branches (should still work)
val4 = 10 if a > 3 else 20
print(val4)

# Case 6: float/int promotion
val5 = 1.5 if True else 10
print(val5)

# Case 7: non-None variable passes through
y2 = "hello"
val6 = y2 if y2 is not None else "default"
print(val6)

# Case 8: chained ternary
x2 = 2
val7 = "low" if x2 < 3 else "mid" if x2 < 7 else "high"
print(val7)

# Case 9: ternary in f-string
name = None
greeting = f"Hello, {name if name is not None else 'stranger'}!"
print(greeting)

# Case 10: ternary with boolean result vs string
check = True
val8 = "found" if check else "missing"
print(val8)

# Case 11: ternary assigning int when True, str when False
val9 = 100 if True else "zero"
print(val9)

# Case 12: ternary inside function
def get_label(x):
    return "positive" if x > 0 else "non-positive"

print(get_label(5))
print(get_label(-3))
