# Test: what type does queue.pop(0) return?
queue = ["A", "B"]
node = queue.pop(0)
print("popped:", node)
print(type(node))

# Does graph[node] work with popped value?
graph = {"A": ["X"], "B": ["Y"]}
# Try direct subscript instead of .get()
print(graph[node])
