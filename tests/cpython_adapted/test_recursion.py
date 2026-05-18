# Adapted from CPython Lib/test/test_call.py and general recursion tests
# Tests recursive function calls

# Simple recursion
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(factorial(0))
print(factorial(1))
print(factorial(5))
print(factorial(10))

# Fibonacci
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

for i in range(12):
    print(fib(i), end=" ")
print()

# Power function
def power(base, exp):
    if exp == 0:
        return 1
    return base * power(base, exp - 1)

print(power(2, 10))
print(power(3, 5))
print(power(5, 0))

# GCD
def gcd(a, b):
    if b == 0:
        return a
    return gcd(b, a % b)

print(gcd(48, 18))
print(gcd(100, 75))
print(gcd(17, 13))
print(gcd(0, 5))

# Sum of list (recursive)
def list_sum(lst):
    if len(lst) == 0:
        return 0
    return lst[0] + list_sum(lst[1:])

print(list_sum([1, 2, 3, 4, 5]))
print(list_sum([10, 20, 30]))
print(list_sum([]))

# Reverse list (recursive)
def reverse_list(lst):
    if len(lst) <= 1:
        return lst
    return reverse_list(lst[1:]) + [lst[0]]

print(reverse_list([1, 2, 3, 4, 5]))
print(reverse_list(["a", "b", "c"]))
print(reverse_list([]))

# Binary search (recursive)
def binary_search(arr, target, lo, hi):
    if lo > hi:
        return -1
    mid = (lo + hi) // 2
    if arr[mid] == target:
        return mid
    if arr[mid] < target:
        return binary_search(arr, target, mid + 1, hi)
    return binary_search(arr, target, lo, mid - 1)

data = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
print(binary_search(data, 7, 0, len(data) - 1))
print(binary_search(data, 1, 0, len(data) - 1))
print(binary_search(data, 19, 0, len(data) - 1))
print(binary_search(data, 6, 0, len(data) - 1))

# Mutual recursion
def is_even(n):
    if n == 0:
        return True
    return is_odd(n - 1)

def is_odd(n):
    if n == 0:
        return False
    return is_even(n - 1)

for i in range(10):
    print(i, is_even(i), is_odd(i))

# Tower of Hanoi count
def hanoi_moves(n):
    if n == 1:
        return 1
    return 2 * hanoi_moves(n - 1) + 1

for i in range(1, 8):
    print(i, hanoi_moves(i))

# Flatten nested list
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result

print(flatten([1, [2, 3], [4, [5, 6]], 7]))
print(flatten([[1, 2], [3, 4], [5, 6]]))
print(flatten([1, 2, 3]))
print(flatten([]))

# Recursive string reverse
def str_reverse(s):
    if len(s) <= 1:
        return s
    return str_reverse(s[1:]) + s[0]

print(str_reverse("hello"))
print(str_reverse("abcdef"))
print(str_reverse("a"))
print(str_reverse(""))
