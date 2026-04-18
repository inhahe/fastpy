# Adversarial patterns — things CPython handles but might trip up the compiler.

# Integer arithmetic edge cases
print(10 // 3)         # 3
print(-10 // 3)        # -4 (floor division)
print(10 % 3)          # 1
print(-10 % 3)         # 2 (Python modulo)
print(2 ** 10)         # 1024
print(2 ** 30 + 2 ** 30)  # 2147483648 (would overflow i32)

# Float edge cases
print(0.1 + 0.2)       # 0.30000000000000004
print(1e100 + 1)       # 1e100
print(float('inf'))    # inf

# String edge cases
s = ""
print(len(s))          # 0
print("a" * 5)         # "aaaaa"
print("a" * 0)         # ""
print("hello"[-1])     # "o"
print("hello"[::-1])   # "olleh"

# List edge cases
print([] + [1])        # [1]
print([1, 2] * 3)      # [1, 2, 1, 2, 1, 2]
print([1, 2, 3][::-1]) # [3, 2, 1]

# Comparison chains
a, b, c = 1, 2, 3
print(a < b < c)       # True
print(a < b > c)       # False

# Boolean short-circuit
def side_effect():
    print("side effect")
    return True

x = False and side_effect()
print(x)               # False (side_effect not called)

# Empty collections truthiness
print(bool([]))        # False
print(bool({}))        # False
print(bool(""))        # False
print(bool(0))         # False
print(bool(1))         # True

# Integer from string
print(int("42"))       # 42
print(int("  42  "))   # 42
print(int("-42"))      # -42

# Range edge cases
print(list(range(3)))         # [0, 1, 2]
print(list(range(0, 10, 2)))  # [0, 2, 4, 6, 8]
print(list(range(10, 0, -1))) # [10, 9, ..., 1]
