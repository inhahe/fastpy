# Regression: FpyValue-typed keys (from list.pop, for-each, etc.)
# crash or return wrong results when used with dict operations.
#
# Bug: dict subscript, dict.get(), and dict stores only handled
# integer (i64) and string (i8*) keys.  When the key was an
# FpyValue struct (e.g. result of list.pop()), the compiler fell
# through to bridge fallback (returning wrong value) or segfaulted.
#
# Also: for-loop iteration over dict.get(key, []) result didn't
# preserve element types — the for variable was typed as INT
# (default), so appending to another list lost the runtime tag.
#
# Fix: Added fpy_val key handling to dict subscript, dict.get(),
# dict store, and dict delete.  Extended _emit_for_list to detect
# lists from dict.get()/setdefault() and use MIXED elem type.

# Case 1: list.pop() result as dict key (subscript)
queue = ["A", "B"]
node = queue.pop(0)
d = {"A": 10, "B": 20}
print(d[node])

# Case 2: list.pop() result as dict.get() key
graph = {"A": ["X"], "B": ["Y"]}
queue2 = ["A", "B"]
n = queue2.pop(0)
print(graph.get(n, []))

# Case 3: BFS pattern — full traversal
graph2 = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}
visited = []
queue3 = ["A"]
while len(queue3) > 0:
    node3 = queue3.pop(0)
    visited.append(node3)
    neighbors = graph2.get(node3, [])
    for nb in neighbors:
        queue3.append(nb)
print(visited)

# Case 4: for-each over dict.get() result preserves types
data = {"x": [1, 2, 3], "y": [4, 5]}
items = data.get("x", [])
result = []
for v in items:
    result.append(v)
print(result)

# Case 5: dict store with FpyValue key
keys = [1, 2, 3]
d2 = {}
for k in keys:
    d2[k] = k * 10
print(sorted(d2.items()))
