# Regression: exception-raising calls inside expressions in try blocks
# Bug: int('invalid') and float('invalid') return 0/0.0 and set the
# exception flag, but the surrounding expression (e.g. list.append())
# executes with the garbage return value BEFORE the exception check
# at statement boundary.
# Fix: added _emit_try_bail_if_exc() after str_to_int and str_to_float
# calls so control transfers to the except handler immediately.

# Case 1: int('abc') inside append in try block
results1 = []
try:
    results1.append(int("abc"))
except ValueError:
    results1.append(-1)
print(results1)

# Case 2: loop with mixed valid/invalid int conversions
results2 = []
for val in ["1", "abc", "3", "", "5"]:
    try:
        results2.append(int(val))
    except ValueError:
        results2.append(-1)
print(results2)

# Case 3: float('invalid') inside append
results3 = []
try:
    results3.append(float("xyz"))
except ValueError:
    results3.append(-1.0)
print(results3)

# Case 4: valid conversions (should not be affected)
results4 = []
try:
    results4.append(int("42"))
    results4.append(float("3.14"))
except ValueError:
    results4.append(-1)
print(results4)

# Case 5: int conversion with base
results5 = []
try:
    results5.append(int("ff", 16))
    results5.append(int("gg", 16))
except ValueError:
    results5.append(-1)
print(results5)
