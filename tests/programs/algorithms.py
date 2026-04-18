# Algorithm test program
# Tests various common algorithms to verify compiler correctness

# --- Bubble sort ---
def bubble_sort(arr):
    n = len(arr)
    result = []
    for x in arr:
        result.append(x)
    for i in range(n):
        for j in range(n - 1 - i):
            if result[j] > result[j + 1]:
                result[j], result[j + 1] = result[j + 1], result[j]
    return result

print(f"sorted: {bubble_sort([64, 34, 25, 12, 22, 11, 90])}")

# --- Binary search ---
def binary_search(arr, target):
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1

data = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
print(f"find 23: index {binary_search(data, 23)}")
print(f"find 99: index {binary_search(data, 99)}")

# --- Fibonacci ---
def fib(n):
    if n <= 1:
        return n
    a = 0
    b = 1
    for i in range(2, n + 1):
        a, b = b, a + b
    return b

for i in range(10):
    print(f"fib({i}) = {fib(i)}")

# --- Prime sieve ---
def sieve(n):
    is_prime = []
    for i in range(n + 1):
        is_prime.append(1)
    is_prime[0] = 0
    is_prime[1] = 0
    for i in range(2, n + 1):
        if is_prime[i] == 1:
            j = i * i
            while j <= n:
                is_prime[j] = 0
                j += i
    primes = []
    for i in range(n + 1):
        if is_prime[i] == 1:
            primes.append(i)
    return primes

print(f"primes < 30: {sieve(30)}")

# --- GCD ---
def gcd(a, b):
    while b:
        a, b = b, a % b
    return a

print(f"gcd(48, 18) = {gcd(48, 18)}")
print(f"gcd(100, 75) = {gcd(100, 75)}")

# --- Power ---
def power(base, exp):
    result = 1
    for i in range(exp):
        result *= base
    return result

print(f"2^10 = {power(2, 10)}")
print(f"3^5 = {power(3, 5)}")
