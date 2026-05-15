# What about list element access?
queue = ["A", "B"]
node = queue[0]
d = {"A": 10, "B": 20}
print("subscript:", d[node])

# vs method call
items = ["A", "B"]
first = items.pop(0)
print("pop:", d[first])

# vs assignment from element in for loop
for x in ["A", "B"]:
    print("for:", d[x])
