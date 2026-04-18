def get_value(d):
    return d["x"]

def sum_values(d):
    return d["a"] + d["b"]

def get_list_len(d):
    return len(d["items"])

print(get_value({"x": 99}))
print(sum_values({"a": 5, "b": 7}))
print(get_list_len({"items": [1, 2, 3, 4]}))
