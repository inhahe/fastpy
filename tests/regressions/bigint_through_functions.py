# Regression test: BigInt values through function calls
# Previously, BigInt values passed through function parameters lost their
# BIGINT tag (treated as regular i64), causing overflow/incorrect results.

# Test 1: BigInt constant through function
def double_it(n):
    return n * 2

big = 10**20
result = double_it(big)
print(result)  # 200000000000000000000

# Test 2: BigInt literal as argument
print(double_it(99999999999999999999))  # 199999999999999999998

# Test 3: BigInt comparison
def is_big(n):
    return n > 10**18

print(is_big(10**20))  # True
print(is_big(42))      # False

# Test 4: BigInt arithmetic in function
def add_big(a, b):
    return a + b

x = 2**63
y = 2**63
print(add_big(x, y))  # 18446744073709551616

# Test 5: BigInt to string
def big_str(n):
    return str(n)

print(big_str(10**30))  # 1000000000000000000000000000000
