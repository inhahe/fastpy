# Regression test: FpyValue-based method dispatch for unknown-type receivers
# Previously, method calls on unannotated parameters crashed because
# the fallback used obj_call_method which assumes FpyObj*.

# Test 1: string method on unannotated parameter
def call_upper(s):
    return s.upper()

result = call_upper("hello")
print(result)  # HELLO

# Test 2: list method on unannotated parameter
def get_length(lst):
    return len(lst)

def append_and_return(lst):
    lst.append(99)
    return lst

nums = [1, 2, 3]
print(get_length(nums))  # 3
result2 = append_and_return([10, 20])
print(len(result2))  # 3

# Test 3: method call on return value of another function
def make_greeting(name):
    return "hello " + name

msg = make_greeting("world")
print(msg.upper())  # HELLO WORLD

# Test 4: chained method calls on unannotated param
def strip_and_upper(s):
    return s.strip().upper()

print(strip_and_upper("  test  "))  # TEST

# Test 5: dict method on unannotated parameter
def get_dict_keys(d):
    return list(d.keys())

keys = get_dict_keys({"a": 1, "b": 2})
print(len(keys))  # 2

# Test 6: function returning list preserves list semantics
def make_list():
    return [10, 20, 30]

lst = make_list()
print(lst[0])  # 10
print(lst[2])  # 30

# Test 7: function returning dict preserves dict semantics
def make_dict():
    return {"a": 1, "b": 2}

d = make_dict()
print(d["a"])  # 1
print(d["b"])  # 2

# Test 8: identity passthrough preserves type
def identity_str(s):
    return s

s = identity_str("hello")
print(s)  # hello
print(s.upper())  # HELLO
