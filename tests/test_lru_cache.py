"""Test functools.lru_cache memoization."""
from functools import lru_cache

@lru_cache(maxsize=128)
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

# Without memoization this would be O(2^n), with cache it's O(n)
print(fib(0))   # 0
print(fib(1))   # 1
print(fib(10))  # 55
print(fib(20))  # 6765
print(fib(30))  # 832040

# Another cached function
@lru_cache
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(factorial(10))  # 3628800
print(factorial(5))   # 120 (from cache — 5! was computed as part of 10!)

print("lru_cache tests passed!")
