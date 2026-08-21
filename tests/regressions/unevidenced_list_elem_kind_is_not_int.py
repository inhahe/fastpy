# Regression: a list whose element kind nothing in the program evidences was
# read back as if it held native ints.
#
# `_get_list_elem_type` / `_infer_type_tag` must hand every caller *some*
# element kind, and answered `VKind.INT` when there was no evidence at all.
# INT therefore meant two different things — "the elements are ints" and "I
# could not tell" — and the three readers that skip the runtime tag on the
# strength of that answer (the inline-GEP paths in `_can_inline_list_access`
# and `_emit_for_list`, and `_emit_subscript`'s `list_get_fv` fallback) picked
# the first reading.  A str pointer then came back as an i64.
#
# The distinction is now carried by the answer itself: the fallback return
# sites hand back the `ELEM_KIND_UNKNOWN` singleton, and a reader that may not
# guess asks `elem_type is ELEM_KIND_UNKNOWN` and declines.
#
# The sentinel is a *return value*, never a field.  The first cut of the fix
# let `_infer_type_tag` record `ValueType(LIST, elem_type=<sentinel>)` into a
# variable's tag; identity does not survive that round trip, so the tag came
# back out as a plain `ValueType(int)` and the fast path returned — laundering
# "I could not tell" into evidence one level up.  Section 1 below is that
# shape, minimised from graphlib's topological sort, where it raised
# `KeyError: 140695993972576` — a pointer used as an integer dict key.

print("--- 1. list(<unrecognised expr>) must not claim to hold ints ---")


def degrees(graph):
    in_degree = {}
    for node in graph:
        in_degree[node] = 0
    for node in graph:
        deps = list(graph[node])
        for dep in deps:
            in_degree[dep] = in_degree[dep] - 1
    return in_degree


print(degrees({"A": ["B"], "B": []}))


print("--- 2. the same list indexed rather than iterated ---")


def first_dep(graph):
    deps = list(graph["A"])
    return deps[0] + "/" + deps[1]


print(first_dep({"A": ["x", "y"], "B": []}))


print("--- 3. sorted()/reversed() of an unrecognised expr, likewise ---")


def sorted_deps(graph):
    out = []
    for k in sorted(graph):
        for d in sorted(graph[k]):
            out.append(d)
    return out


print(sorted_deps({"b": ["q", "p"], "a": ["z"]}))


def reversed_deps(graph):
    out = []
    for d in reversed(list(graph["a"])):
        out.append(d)
    return out


print(reversed_deps({"a": ["one", "two", "three"]}))


print("--- 4. range() keeps its evidence: its elements really are ints ---")


def sum_range():
    total = 0
    for i in range(5):
        total = total + i
    xs = list(range(4))
    return total + xs[0] + xs[3]


print(sum_range())


print("--- 5. list(d.values()) over non-int values ---")


def join_values():
    d = {"a": "alpha", "b": "beta"}
    vals = list(d.values())
    out = []
    for v in vals:
        out.append(len(v))
    return out


print(join_values())


print("--- 6. floats survive the round trip too ---")


def sum_float_deps(graph):
    vals = list(graph["k"])
    total = 0.0
    for v in vals:
        total = total + v
    return total


print(sum_float_deps({"k": [1.5, 2.25]}))


print("--- 7. a genuinely int-holding list still adds up ---")


def sum_int_deps(graph):
    vals = list(graph["k"])
    total = 0
    for v in vals:
        total = total + v
    return total


print(sum_int_deps({"k": [10, 20, 30]}))


print("--- 8. the full topological sort the regression came from ---")


def topological_sort(graph):
    in_degree = {}
    for node in graph:
        if node not in in_degree:
            in_degree[node] = 0
        for dep in graph[node]:
            if dep not in in_degree:
                in_degree[dep] = 0
            in_degree[dep] = in_degree[dep] + 1

    queue = []
    for node in in_degree:
        if in_degree[node] == 0:
            queue.append(node)
    queue.sort()

    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        if node in graph:
            deps = list(graph[node])
            deps.sort()
            for dep in deps:
                in_degree[dep] = in_degree[dep] - 1
                if in_degree[dep] == 0:
                    queue.append(dep)
                    queue.sort()

    if len(result) != len(in_degree):
        raise ValueError("cycle detected")
    return result


print(topological_sort({"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}))
print(topological_sort({"x": ["y", "z"], "y": ["w"], "z": ["w"], "w": []}))
print(topological_sort({"a": [], "b": ["a"], "c": ["a", "b"]}))
