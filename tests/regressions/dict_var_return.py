def make_dict():
    d = {"name": "alice", "age": 30}
    return d

def make_and_modify():
    d = {}
    d["x"] = 10
    d["y"] = 20
    return d

result = make_dict()
print(result["name"])
print(result["age"])

m = make_and_modify()
print(m["x"])
print(m["y"])
