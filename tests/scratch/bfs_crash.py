graph = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}
visited = []
queue = ["A"]
while len(queue) > 0:
    node = queue.pop(0)
    visited.append(node)
    neighbors = graph.get(node, [])
    for n in neighbors:
        queue.append(n)
print(visited)
