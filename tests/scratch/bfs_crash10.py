# Trace: iterate over graph.get() result
graph = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}
node = "A"
neighbors = graph.get(node, [])
print("neighbors:", neighbors)
print("type:", type(neighbors))
for n in neighbors:
    print("item:", n)
