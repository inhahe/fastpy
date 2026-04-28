# Regression: cross-category mixed-type function parameters
# Tests that functions called with arguments from different type categories
# (int=i64, str/list=pointer) dispatch operations correctly at runtime.
# The key challenge is that post-merge cleanup clears the merged type to None
# when categories conflict, and the param tag must be set to "mixed" (not
# "str" or "int") to enable correct runtime dispatch.

# isinstance() + len() on cross-category types
def process(x):
    if isinstance(x, str):
        print("str:", x)
    elif isinstance(x, int):
        print("int:", x)
    elif isinstance(x, list):
        print("list:", len(x))

process("hello")     # str: hello
process(42)          # int: 42
process([1, 2, 3])   # list: 3

# isinstance() with all major type categories
def describe(x):
    if isinstance(x, int):
        return "integer"
    elif isinstance(x, str):
        return "string"
    elif isinstance(x, list):
        return "list"
    elif isinstance(x, dict):
        return "dict"
    else:
        return "other"

print(describe(10))           # integer
print(describe("abc"))        # string
print(describe([1, 2]))       # list
print(describe({"a": 1}))     # dict

# len() after isinstance guard
def safe_len(x):
    if isinstance(x, (str, list, dict)):
        return len(x)
    return -1

print(safe_len("hello"))      # 5
print(safe_len([1, 2, 3]))    # 3
print(safe_len({"a": 1}))     # 1
print(safe_len(42))           # -1
