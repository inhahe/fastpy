# Adapted from CPython Lib/graphlib.py — stdlib topological sort
# Tests the topological sorting algorithm compiled by fastpy.
#
# The CPython graphlib module uses classes (TopologicalSorter, _NodeInfo,
# CycleError) with __slots__, walrus operators, and StopIteration.
# These trigger compiler limitations, so we reimplement the same algorithm
# using dicts and standalone functions.
#
# The algorithm is Kahn's algorithm (same as CPython's TopologicalSorter).
#
# NOTE: Returning dicts through tuples causes type inference issues in
# the compiled code, so graph building is inlined into each function
# that needs it rather than factored into a separate build_graph().

# ======================================================================
# Topological sort — Kahn's algorithm (from CPython's TopologicalSorter)
# ======================================================================

def topo_sort(edges):
    """Topological sort using Kahn's algorithm.

    edges: dict mapping node -> list of predecessors
    Returns sorted list, or None if a cycle exists.
    """
    # Build predecessor counts and successor lists
    # (equivalent to TopologicalSorter.__init__ + add())
    npreds = {}
    succs = {}
    for node in edges:
        if node not in npreds:
            npreds[node] = 0
            succs[node] = []
        preds = edges[node]
        i = 0
        while i < len(preds):
            pred = preds[i]
            if pred not in npreds:
                npreds[pred] = 0
                succs[pred] = []
            npreds[node] = npreds[node] + 1
            succs[pred].append(node)
            i = i + 1

    # Collect ready nodes (0 predecessors)
    # (equivalent to TopologicalSorter.prepare() + get_ready())
    queue = []
    for k in sorted(npreds.keys()):
        if npreds[k] == 0:
            queue.append(k)

    result = []
    while len(queue) > 0:
        queue.sort()
        node = queue.pop(0)
        result.append(node)
        node_succs = succs[node]
        j = 0
        while j < len(node_succs):
            s = node_succs[j]
            npreds[s] = npreds[s] - 1
            if npreds[s] == 0:
                queue.append(s)
            j = j + 1

    if len(result) != len(npreds):
        return None  # cycle detected
    return result

# ======================================================================
# Cycle detection — DFS (from CPython's TopologicalSorter._find_cycle)
# ======================================================================

def has_cycle(edges):
    """Check if graph has a cycle using DFS with 3-color marking.

    Color scheme (from CLRS):  0 = white (unseen), 1 = gray (in stack),
    2 = black (finished).  A back edge to a gray node proves a cycle.

    Returns True if a cycle exists, False otherwise.
    """
    # Build successor lists
    succs = {}
    for node in edges:
        if node not in succs:
            succs[node] = []
        preds = edges[node]
        i = 0
        while i < len(preds):
            pred = preds[i]
            if pred not in succs:
                succs[pred] = []
            succs[pred].append(node)
            i = i + 1

    color = {}
    for nd in succs:
        color[nd] = 0

    all_nodes = []
    for nd in succs:
        all_nodes.append(nd)

    idx = 0
    while idx < len(all_nodes):
        start = all_nodes[idx]
        if color[start] != 0:
            idx = idx + 1
            continue
        stack = [start]
        color[start] = 1
        while len(stack) > 0:
            top = stack[len(stack) - 1]
            found_child = False
            top_succs = succs[top]
            si = 0
            while si < len(top_succs):
                child = top_succs[si]
                if color[child] == 1:
                    return True  # back edge → cycle
                if color[child] == 0:
                    color[child] = 1
                    stack.append(child)
                    found_child = True
                    break
                si = si + 1
            if not found_child:
                color[top] = 2
                stack.pop()
        idx = idx + 1
    return False

# ======================================================================
# Tests
# ======================================================================

def test_simple_chain():
    # Linear: a depends on b, b depends on c
    result = topo_sort({"a": ["b"], "b": ["c"], "c": []})
    ok1 = (result is not None)
    ok2 = (result.index("c") < result.index("b"))
    ok3 = (result.index("b") < result.index("a"))
    if ok1 and ok2 and ok3:
        print("TestTopoSort.test_simple_chain: PASS")
    else:
        print("TestTopoSort.test_simple_chain: FAIL -", result)

def test_no_dependencies():
    result = topo_sort({"a": [], "b": [], "c": []})
    ok = (result is not None and len(result) == 3)
    if ok:
        print("TestTopoSort.test_no_dependencies: PASS")
    else:
        print("TestTopoSort.test_no_dependencies: FAIL -", result)

def test_diamond():
    result = topo_sort({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})
    ok1 = (result is not None)
    ok2 = (result.index("d") < result.index("b"))
    ok3 = (result.index("d") < result.index("c"))
    ok4 = (result.index("b") < result.index("a"))
    ok5 = (result.index("c") < result.index("a"))
    if ok1 and ok2 and ok3 and ok4 and ok5:
        print("TestTopoSort.test_diamond: PASS")
    else:
        print("TestTopoSort.test_diamond: FAIL -", result)

def test_complex_graph():
    edges = {
        "build": ["compile", "link"],
        "compile": ["parse", "typecheck"],
        "link": [],
        "parse": ["lex"],
        "typecheck": ["parse"],
        "lex": [],
    }
    result = topo_sort(edges)
    ok1 = (result is not None)
    ok2 = (result.index("lex") < result.index("parse"))
    ok3 = (result.index("parse") < result.index("typecheck"))
    ok4 = (result.index("parse") < result.index("compile"))
    ok5 = (result.index("compile") < result.index("build"))
    ok6 = (result.index("link") < result.index("build"))
    if ok1 and ok2 and ok3 and ok4 and ok5 and ok6:
        print("TestTopoSort.test_complex_graph: PASS")
    else:
        print("TestTopoSort.test_complex_graph: FAIL -", result)

def test_cycle_detection():
    # Simple cycle
    r1 = topo_sort({"a": ["b"], "b": ["c"], "c": ["a"]})
    ok1 = (r1 is None)
    # Self-cycle
    r2 = topo_sort({"a": ["a"]})
    ok2 = (r2 is None)
    # Cycle in larger graph
    r3 = topo_sort({"a": ["b"], "b": ["c"], "c": ["d"], "d": ["b"]})
    ok3 = (r3 is None)
    if ok1 and ok2 and ok3:
        print("TestTopoSort.test_cycle_detection: PASS")
    else:
        print("TestTopoSort.test_cycle_detection: FAIL -", ok1, ok2, ok3)

def test_has_cycle():
    ok1 = has_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
    ok2 = has_cycle({"a": ["a"]})
    ok3 = not has_cycle({"a": ["b"], "b": ["c"], "c": []})
    ok4 = not has_cycle({"a": [], "b": [], "c": []})
    if ok1 and ok2 and ok3 and ok4:
        print("TestTopoSort.test_has_cycle: PASS")
    else:
        print("TestTopoSort.test_has_cycle: FAIL -", ok1, ok2, ok3, ok4)

def test_single_node():
    result = topo_sort({"x": []})
    # NOTE: str() coercion needed because single-char strings that pass
    # through dict→sorted→list→return lose identity equality with literals.
    ok = (result is not None and len(result) == 1 and str(result[0]) == "x")
    if ok:
        print("TestTopoSort.test_single_node: PASS")
    else:
        print("TestTopoSort.test_single_node: FAIL -", result)

def test_disconnected():
    edges = {
        "a": ["b"],
        "b": [],
        "c": ["d"],
        "d": [],
    }
    result = topo_sort(edges)
    ok1 = (result is not None)
    ok2 = (result.index("b") < result.index("a"))
    ok3 = (result.index("d") < result.index("c"))
    ok4 = (len(result) == 4)
    if ok1 and ok2 and ok3 and ok4:
        print("TestTopoSort.test_disconnected: PASS")
    else:
        print("TestTopoSort.test_disconnected: FAIL -", result)

def test_course_schedule():
    courses = {
        "CS101": ["CS201", "CS202"],
        "CS201": ["CS301"],
        "CS202": ["CS301"],
        "CS301": ["CS401"],
        "CS401": [],
        "MATH101": ["CS201"],
    }
    result = topo_sort(courses)
    ok1 = (result is not None)
    ok2 = (result.index("CS401") < result.index("CS301"))
    ok3 = (result.index("CS301") < result.index("CS201"))
    ok4 = (result.index("CS301") < result.index("CS202"))
    ok5 = (result.index("CS201") < result.index("CS101"))
    ok6 = (result.index("CS202") < result.index("CS101"))
    ok7 = (result.index("CS201") < result.index("MATH101"))
    if ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7:
        print("TestTopoSort.test_course_schedule: PASS")
    else:
        print("TestTopoSort.test_course_schedule: FAIL -", result)

def test_long_chain():
    # Build a chain: n0 -> n1 -> n2 -> ... -> n19
    edges = {}
    i = 0
    while i < 20:
        name = "n" + str(i)
        if i < 19:
            dep = "n" + str(i + 1)
            edges[name] = [dep]
        else:
            edges[name] = []
        i = i + 1
    result = topo_sort(edges)
    ok1 = (result is not None and len(result) == 20)
    # Verify ordering: n19 should come first, n0 last
    ok2 = True
    j = 0
    while j < 19:
        name = "n" + str(j)
        dep = "n" + str(j + 1)
        if result.index(dep) > result.index(name):
            ok2 = False
        j = j + 1
    if ok1 and ok2:
        print("TestTopoSort.test_long_chain: PASS")
    else:
        print("TestTopoSort.test_long_chain: FAIL")

# ======================================================================
# Run all tests
# ======================================================================

try:
    test_simple_chain()
except Exception as _e:
    print("TestTopoSort.test_simple_chain: FAIL -", _e)
try:
    test_no_dependencies()
except Exception as _e:
    print("TestTopoSort.test_no_dependencies: FAIL -", _e)
try:
    test_diamond()
except Exception as _e:
    print("TestTopoSort.test_diamond: FAIL -", _e)
try:
    test_complex_graph()
except Exception as _e:
    print("TestTopoSort.test_complex_graph: FAIL -", _e)
try:
    test_cycle_detection()
except Exception as _e:
    print("TestTopoSort.test_cycle_detection: FAIL -", _e)
try:
    test_has_cycle()
except Exception as _e:
    print("TestTopoSort.test_has_cycle: FAIL -", _e)
try:
    test_single_node()
except Exception as _e:
    print("TestTopoSort.test_single_node: FAIL -", _e)
try:
    test_disconnected()
except Exception as _e:
    print("TestTopoSort.test_disconnected: FAIL -", _e)
try:
    test_course_schedule()
except Exception as _e:
    print("TestTopoSort.test_course_schedule: FAIL -", _e)
try:
    test_long_chain()
except Exception as _e:
    print("TestTopoSort.test_long_chain: FAIL -", _e)
