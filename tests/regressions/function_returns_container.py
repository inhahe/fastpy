def make_dict():
    return {"a": 1, "b": 2}

def make_list():
    return [10, 20, 30]

def make_str():
    return "hi"

def make_dict_with_list():
    return {"items": [1, 2, 3]}

d = make_dict()
print(d["a"])
print(d["b"])

lst = make_list()
print(lst[0])
print(lst[2])

s = make_str()
print(s)

d2 = make_dict_with_list()
print(d2["items"])
