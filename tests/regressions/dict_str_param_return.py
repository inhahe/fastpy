def get_name(d):
    return d["name"]

def concat_values(d):
    return d["a"] + d["b"]

print(get_name({"name": "alice"}))
print(get_name({"name": "bob"}))
print(concat_values({"a": "hello", "b": " world"}))
