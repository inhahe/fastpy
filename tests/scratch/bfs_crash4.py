# Does the crash relate to queue.pop(0)?
queue = ["A", "B"]
node = queue.pop(0)
print("popped:", node)
print("queue after pop:", queue)

# Now try graph.get with the popped value
graph = {"A": ["X"], "B": ["Y"]}
neighbors = graph.get(node, [])
print("neighbors:", neighbors)
