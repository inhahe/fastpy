def test(graph):
    in_degree = {"a": 0, "b": 1, "c": 1}
    node = "a"
    # Without sorted - iterate directly
    for dep in graph[node]:
        print("direct dep:", dep, "lookup:", in_degree[dep])
    # With sorted
    for dep in sorted(graph[node]):
        print("sorted dep:", dep, "lookup:", in_degree[dep])

graph1 = {"a": ["b"], "b": ["c"], "c": []}
test(graph1)
