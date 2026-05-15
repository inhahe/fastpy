# Regression: cross-type comparison crashes
# Previously, comparing INT with LIST (or STR with INT) crashed because:
# 1. Type-specific compare paths (STR, LIST) only checked left_kind,
#    assumed right side matched → dereferenced wrong type as string ptr
# 2. Legacy i64+ptr fallback treated INT as string pointer → null deref
# 3. fv_compare didn't raise TypeError for incompatible ordering

# Equality between different types should return False/True
print(0 == [])       # False
print(0 != [])       # True
print([] == 0)       # False
print([] != 0)       # True
print("a" == 1)      # False
print("a" != 1)      # True

# Same-type comparisons still work
print(1 < 2)         # True
print("a" < "b")     # True
print([1] == [1])    # True

# int/float cross-comparison works
print(1 < 2.5)       # True
print(1 == 1.0)      # True

# Ordering between incompatible types raises TypeError
try:
    0 < []
except TypeError:
    print("caught TypeError: int < list")

try:
    "a" < 1
except TypeError:
    print("caught TypeError: str < int")
