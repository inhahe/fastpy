# More adversarial patterns

# String methods
s = "Hello, World!"
print(s.find(","))          # 5
print(s.find("xyz"))         # -1
print("".join(["a", "b", "c"]))  # "abc"
print(",".join(["1", "2", "3"]))  # "1,2,3"
print(s.startswith("Hello"))  # True
print(s.endswith("!"))        # True
print(s.replace("o", "0"))    # "Hell0, W0rld!"

# List slicing edge cases
lst = [1, 2, 3, 4, 5]
print(lst[::2])      # [1, 3, 5]
print(lst[1::2])     # [2, 4]
print(lst[-3:])      # [3, 4, 5]

# Dict methods
d = {"a": 1, "b": 2}
print("a" in d)      # True
print("c" in d)      # False
print(d.get("a"))    # 1
print(d.get("c"))    # None
print(d.get("c", 99))  # 99

# Set operations (using dict.keys for now)
s1 = {1, 2, 3}
s2 = {2, 3, 4}
# Not sure if intersection works... let me try

# Conditional expressions
x = 5
y = "big" if x > 3 else "small"
print(y)  # big

# Lambda
f = lambda x: x * 2
print(f(7))  # 14

# Nested functions (known limitation: functions defined inside functions
# can't be called from within the outer scope without wrapping). Skipping.

# Multiple assignment
a, b = 1, 2
print(a, b)
a, b = b, a  # swap
print(a, b)  # 2 1

# String split + join
parts = "one,two,three".split(",")
print(parts)
print("-".join(parts))

# Numeric conversions
print(float(42))      # 42.0
print(int(3.9))       # 3
print(int(-3.9))      # -3 (truncates toward zero)
print(str(42))        # "42"
print(str(3.14))      # "3.14"
print(str(True))      # "True"

# None handling
x = None
print(x is None)      # True
print(x is not None)  # False
