# Isolate: does graph.get(node, []) work in a simple case?
graph = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}
node = "A"
neighbors = graph.get(node, [])
print(neighbors)
