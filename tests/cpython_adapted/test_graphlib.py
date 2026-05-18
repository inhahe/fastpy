# Adapted from CPython Lib/test/test_graphlib.py
# Tests topological sort (pure Python implementation)
#
# NOTE: sorted(graph[node]) loses string elem type through the sorted()
# wrapper when graph is a function parameter.  Work around by iterating
# graph[node] directly and sorting 'queue' instead, which preserves
# determinism while keeping keys in a context the compiler can track.

def topological_sort(graph):
    """Kahn's algorithm for topological sort."""
    # Calculate in-degrees
    in_degree = {}
    for node in graph:
        if node not in in_degree:
            in_degree[node] = 0
        for dep in graph[node]:
            if dep not in in_degree:
                in_degree[dep] = 0
            in_degree[dep] = in_degree[dep] + 1

    # Start with nodes that have no dependencies
    queue = []
    for node in sorted(in_degree.keys()):
        if in_degree[node] == 0:
            queue.append(node)

    result = []
    while len(queue) > 0:
        queue.sort()  # sort queue for determinism instead of deps
        node = queue.pop(0)
        result.append(node)
        if node in graph:
            for dep in graph[node]:
                in_degree[dep] = in_degree[dep] - 1
                if in_degree[dep] == 0:
                    queue.append(dep)

    if len(result) != len(in_degree):
        return None  # cycle detected
    return result

# Simple linear chain
graph1 = {"a": ["b"], "b": ["c"], "c": []}
print(topological_sort(graph1))

# Diamond
graph2 = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
result = topological_sort(graph2)
# Verify ordering constraints
print(result.index("a") < result.index("b"))
print(result.index("a") < result.index("c"))
print(result.index("b") < result.index("d"))
print(result.index("c") < result.index("d"))

# No dependencies
graph3 = {"a": [], "b": [], "c": []}
print(sorted(topological_sort(graph3)))

# Complex graph
graph4 = {
    "build": ["compile", "link"],
    "compile": ["parse", "typecheck"],
    "link": [],
    "parse": ["lex"],
    "typecheck": ["parse"],
    "lex": [],
}
result4 = topological_sort(graph4)
print(result4 is not None)
# Verify all constraints
print(result4.index("build") < result4.index("compile"))
print(result4.index("build") < result4.index("link"))
print(result4.index("compile") < result4.index("parse"))
print(result4.index("compile") < result4.index("typecheck"))
print(result4.index("parse") < result4.index("lex"))
print(result4.index("typecheck") < result4.index("parse"))

# Cycle detection
graph_cycle = {"a": ["b"], "b": ["c"], "c": ["a"]}
print(topological_sort(graph_cycle))  # None

# Self-cycle
graph_self = {"a": ["a"]}
print(topological_sort(graph_self))  # None

# Single node
graph_single = {"x": []}
print(topological_sort(graph_single))

# Disconnected components
graph_disconnected = {
    "a": ["b"],
    "b": [],
    "c": ["d"],
    "d": [],
}
result_disc = topological_sort(graph_disconnected)
print(result_disc.index("a") < result_disc.index("b"))
print(result_disc.index("c") < result_disc.index("d"))

# Course schedule pattern
courses = {
    "CS101": ["CS201", "CS202"],
    "CS201": ["CS301"],
    "CS202": ["CS301"],
    "CS301": ["CS401"],
    "CS401": [],
    "MATH101": ["CS201"],
}
schedule = topological_sort(courses)
print(schedule is not None)
print(schedule.index("CS101") < schedule.index("CS201"))
print(schedule.index("CS101") < schedule.index("CS202"))
print(schedule.index("CS201") < schedule.index("CS301"))
print(schedule.index("CS301") < schedule.index("CS401"))
print(schedule.index("MATH101") < schedule.index("CS201"))
