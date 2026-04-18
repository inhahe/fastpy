def identity_dict(d):
    return d

def identity_list(lst):
    return lst

def identity_str(s):
    return s

result = identity_dict({"a": 1, "b": 2})
print(result["a"])
print(result["b"])

lst = identity_list([10, 20, 30])
print(lst[0])
print(lst[2])

s = identity_str("hello")
print(s)
print(s.upper())
