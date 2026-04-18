# Algorithmic patterns

# Fibonacci iterative
def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
print(fib(20))  # 6765

# Recursive factorial
def fact(n):
    if n <= 1:
        return 1
    return n * fact(n - 1)
print(fact(10))  # 3628800

# Bubble sort
def bsort(lst):
    n = len(lst)
    for i in range(n):
        for j in range(n - i - 1):
            if lst[j] > lst[j + 1]:
                lst[j], lst[j + 1] = lst[j + 1], lst[j]
    return lst
print(bsort([5, 3, 8, 1, 2]))  # [1, 2, 3, 5, 8]

# Prime sieve
def sieve(n):
    is_prime = [True] * (n + 1)
    is_prime[0] = False
    is_prime[1] = False
    primes = []
    for i in range(2, n + 1):
        if is_prime[i]:
            primes.append(i)
            j = i * i
            while j <= n:
                is_prime[j] = False
                j += i
    return primes
print(sieve(30))  # [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]

# Count chars (dict:int value-type inference through the loop)
def count_chars(s):
    counts = {}
    for c in s:
        if c in counts:
            counts[c] = counts[c] + 1
        else:
            counts[c] = 1
    return counts

result = count_chars("hello world")
for c in sorted(result.keys()):
    print(c, result[c])

# Binary search
def bsearch(lst, target):
    lo, hi = 0, len(lst) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if lst[mid] == target:
            return mid
        elif lst[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
print(bsearch([1, 3, 5, 7, 9, 11], 7))  # 3
print(bsearch([1, 3, 5, 7, 9, 11], 6))  # -1

# Reverse a string via list
def reverse_str(s):
    chars = []
    for c in s:
        chars.append(c)
    result = ""
    i = len(chars) - 1
    while i >= 0:
        result = result + chars[i]
        i = i - 1
    return result
print(reverse_str("hello"))  # olleh

# Sum of squares
total = 0
for i in range(1, 11):
    total = total + i * i
print(total)  # 385

# GCD
def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a
print(gcd(48, 36))  # 12
