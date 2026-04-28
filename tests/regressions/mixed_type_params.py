# Regression: mixed-type function parameters (same pointer category)
# Tests that functions called with different pointer types (str, list, dict)
# dispatch operations correctly via runtime tag checking.

# len() on mixed types
def get_len(x):
    return len(x)

print(get_len("abc"))          # 3
print(get_len([1, 2, 3]))     # 3
print(get_len({"a": 1}))      # 1

# print on mixed types
def show(x):
    print(x)

show("hello")                  # hello
show([1, 2])                   # [1, 2]

# return on mixed types
def identity(x):
    return x

a = identity("hello")
print(a)                       # hello
b = identity([1, 2, 3])
print(b)                       # [1, 2, 3]
