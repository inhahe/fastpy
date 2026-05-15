# Test: is graph.get(node, []) the issue when node is a variable vs literal?
graph = {"A": ["X"], "B": ["Y"]}

# Literal key works (from bfs_crash2)
r1 = graph.get("A", [])
print("literal:", r1)

# Variable from assignment
node = "A"
r2 = graph.get(node, [])
print("var:", r2)

# Variable from list indexing
keys = ["A", "B"]
node2 = keys[0]
r3 = graph.get(node2, [])
print("indexed:", r3)
