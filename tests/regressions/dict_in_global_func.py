# Regression: dict 'in' operator with variables inside functions
# accessing global dicts. String variables stored as FpyValues were
# misrouted to dict_has_int_key; also _infer_type_tag / _is_dict_expr
# didn't check _global_vars so global dicts weren't recognized inside
# functions.

# String-keyed global dict
cache = {"hello": 10, "world": 20}

# Literal string at module level (baseline)
print("hello" in cache)      # True
print("missing" in cache)    # False

# String variable inside function
def check_str():
    x = "hello"
    print(x in cache)         # True
    y = "missing"
    print(y in cache)         # False
    print(x not in cache)     # False
    print(y not in cache)     # True

check_str()

# Int-keyed global dict
nums = {1: "a", 2: "b", 3: "c"}
print(1 in nums)              # True
print(99 in nums)             # False

def check_int():
    k = 2
    print(k in nums)          # True
    m = 99
    print(m in nums)          # False

check_int()
