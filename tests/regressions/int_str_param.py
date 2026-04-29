# Regression: int(s) and float(s) where s is a string parameter
# The FV-backed int() path only checked for float tags;
# string-tagged values returned raw pointers instead of
# calling str_to_int. Same bug for float() — string params
# were interpreted as raw pointer bits via sitofp.

def parse_int(s):
    return int(s)

print(parse_int("42"))     # 42
print(parse_int("-100"))   # -100
print(parse_int("0"))      # 0

def parse_float(s):
    return float(s)

print(parse_float("3.14"))  # 3.14

# int() with various types
def to_int(x):
    return int(x)

print(to_int(42))     # 42 (already int)
print(to_int(3.7))    # 3  (float truncation)
print(to_int("99"))   # 99 (string parsing)

# In try/except pattern
def safe_parse(s):
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s

print(safe_parse("42"))     # 42
print(safe_parse("3.14"))   # 3.14
print(safe_parse("hello"))  # hello

# float() with various types
def to_float(x):
    return float(x)

print(to_float("3.14"))  # 3.14
print(to_float("42"))    # 42.0
print(to_float(42))      # 42.0
print(to_float(3.14))    # 3.14
