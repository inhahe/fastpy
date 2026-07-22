# Minimal: list.pop(0) as dict key
queue = ["A", "B"]
node = queue.pop(0)
# Is node treated as string or int?
d = {"A": 10, "B": 20}
# Try string concat to check if it's a string
print(node + "!")
# Try as dict key
print(d[node])
