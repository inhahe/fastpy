# Regression: BoolOp (and/or) on boolean operands should print True/False
# Before fix: `x and y` where both are bool printed "0" or "1" because the
# BoolOp uses an i64 alloca internally, losing the bool vs. int distinction.
# Fix: _wrap_for_print recognizes BoolOp with all-boolean operands and
# tags the result as BOOL (tag=3) instead of INT (tag=0).

x = True
y = False

print(x and y)
print(x or y)
print(not x)

a = True
b = True
c = False
print(a and b and c)
print(a or b or c)

# Mixed: int operands should stay int
print(1 and 2)
print(0 or 5)

# In f-strings
print(f"and={x and y}")
print(f"or={x or y}")
