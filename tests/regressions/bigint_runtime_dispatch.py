# Regression: BigInt through runtime dispatch paths
# Tests BIGINT tag in FpyValue for lists, dicts, sorting, truthiness,
# and runtime binop/compare.

# BigInt in dict values
d = {"a": 100000000000000000000, "b": 200000000000000000000}
print(d["a"])         # 100000000000000000000
print(d["b"])         # 200000000000000000000

# BigInt in list literals
nums = [300000000000000000000, 100000000000000000000, 200000000000000000000]
print(nums)           # [300000000000000000000, 100000000000000000000, 200000000000000000000]

# Sorted BigInts
print(sorted(nums))   # [100000000000000000000, 200000000000000000000, 300000000000000000000]

# BigInt truthiness
big = 100000000000000000000
if big:
    print("True")
else:
    print("False")

# BigInt variables in list
a = 10**20
b = 10**30
lst = [a, b, 42]
print(lst)            # [100000000000000000000, 1000000000000000000000000000000, 42]
