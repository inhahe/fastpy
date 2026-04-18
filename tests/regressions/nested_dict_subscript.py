d = {"a": {"b": 1, "c": 2}, "x": {"b": 10, "c": 20}}
print(d["a"]["b"])
print(d["a"]["c"])
print(d["x"]["b"])
print(d["x"]["c"])

items = [{"name": "first", "v": 1}, {"name": "second", "v": 2}]
for i in items:
    print(i["name"], i["v"])
