# Adapted from CPython Lib/test/test_iter.py
# Tests iteration protocol and iterators

# Basic iteration
for x in [1, 2, 3, 4, 5]:
    print(x)

# Iteration over string
chars = []
for c in "hello":
    chars.append(c)
print(chars)

# Iteration over tuple
total = 0
for x in (10, 20, 30, 40, 50):
    total += x
print(total)

# Iteration over dict keys
d = {"a": 1, "b": 2, "c": 3}
keys = []
for k in d:
    keys.append(k)
print(sorted(keys))

# Iteration over dict items
pairs = []
for k, v in d.items():
    pairs.append((k, v))
print(sorted(pairs))

# Iteration over range
result = []
for i in range(0, 20, 3):
    result.append(i)
print(result)

# Break in iteration
found = -1
for i, x in enumerate([10, 20, 30, 40, 50]):
    if x == 30:
        found = i
        break
print(found)

# Continue in iteration
evens = []
for x in range(10):
    if x % 2 != 0:
        continue
    evens.append(x)
print(evens)

# Nested iteration
products = []
for i in range(1, 4):
    for j in range(1, 4):
        products.append(i * j)
print(products)

# For-else (no break)
def find_prime(limit):
    for n in range(2, limit):
        for d in range(2, n):
            if n % d == 0:
                break
        else:
            print(n, end=" ")
    print()

find_prime(20)

# Unpacking in iteration
pairs = [(1, "a"), (2, "b"), (3, "c")]
for num, letter in pairs:
    print(num, letter)

# Iteration with accumulator
def running_max(lst):
    result = []
    current_max = lst[0]
    for x in lst:
        if x > current_max:
            current_max = x
        result.append(current_max)
    return result

print(running_max([3, 1, 4, 1, 5, 9, 2, 6]))

# Iteration building a dict
word = "abracadabra"
freq = {}
for ch in word:
    if ch in freq:
        freq[ch] = freq[ch] + 1
    else:
        freq[ch] = 1
print(sorted(freq.items()))

# Custom iterable class
class Countdown:
    def __init__(self, start):
        self.current = start

    def __iter__(self):
        return self

    def __next__(self):
        if self.current <= 0:
            raise StopIteration
        val = self.current
        self.current -= 1
        return val

print(list(Countdown(5)))
print(list(Countdown(3)))

# Sum, min, max on iterables
nums = [5, 2, 8, 1, 9, 3, 7]
print(sum(nums))
print(min(nums))
print(max(nums))

# all() and any() patterns
def all_positive(lst):
    for x in lst:
        if x <= 0:
            return False
    return True

def any_negative(lst):
    for x in lst:
        if x < 0:
            return True
    return False

print(all_positive([1, 2, 3, 4]))
print(all_positive([1, 2, -3, 4]))
print(any_negative([1, 2, 3]))
print(any_negative([1, -2, 3]))
