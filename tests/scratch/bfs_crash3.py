# Isolate: graph.get in a loop
graph = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}
queue = ["A"]
node = queue.pop(0)
print("node:", node)
neighbors = graph.get(node, [])
print("neighbors:", neighbors)
for n in neighbors:
    print("n:", n)
    queue.append(n)
print("queue:", queue)
