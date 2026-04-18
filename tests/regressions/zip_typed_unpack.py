keys = ["a", "b", "c"]
vals = [1, 2, 3]
d = {}
for k, v in zip(keys, vals):
    d[k] = v
print(d["a"])
print(d["b"])
print(d["c"])

for name, score in zip(["alice", "bob"], [90, 85]):
    print(name, score)
