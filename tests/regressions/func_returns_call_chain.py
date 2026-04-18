def sort_list(lst):
    return sorted(lst)

def keys_sorted(d):
    return sorted(d.keys())

def first_half(lst):
    return lst[:len(lst) // 2]

def concat(a, b):
    return a + b

def repeat(s, n):
    return s * n

def chain(s):
    return s.strip().upper()

print(sort_list([3, 1, 2, 5, 4]))
print(keys_sorted({"b": 1, "a": 2, "c": 3}))
print(first_half([1, 2, 3, 4, 5, 6]))
print(concat("hello", " world"))
print(repeat("ab", 3))
print(chain("  hello  "))
