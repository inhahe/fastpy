# Auto-adapted from CPython Lib/test/test_graphlib.py
# Tests fastpy's ability to compile and run the graphlib module
# Stdlib source inlined from: C:\Users\inhah\AppData\Local\Python\pythoncore-3.13-64\Lib\graphlib.py

# ======================================================================
# Inlined stdlib module: graphlib
# ======================================================================

from types import GenericAlias

__all__ = ["TopologicalSorter", "CycleError"]

_NODE_OUT = -1
_NODE_DONE = -2


class _NodeInfo:
    __slots__ = "node", "npredecessors", "successors"

    def __init__(self, node):
        # The node this class is augmenting.
        self.node = node

        # Number of predecessors, generally >= 0. When this value falls to 0,
        # and is returned by get_ready(), this is set to _NODE_OUT and when the
        # node is marked done by a call to done(), set to _NODE_DONE.
        self.npredecessors = 0

        # List of successor nodes. The list can contain duplicated elements as
        # long as they're all reflected in the successor's npredecessors attribute.
        self.successors = []


class CycleError(ValueError):
    """Subclass of ValueError raised by TopologicalSorter.prepare if cycles
    exist in the working graph.

    If multiple cycles exist, only one undefined choice among them will be reported
    and included in the exception. The detected cycle can be accessed via the second
    element in the *args* attribute of the exception instance and consists in a list
    of nodes, such that each node is, in the graph, an immediate predecessor of the
    next node in the list. In the reported list, the first and the last node will be
    the same, to make it clear that it is cyclic.
    """

    pass


class TopologicalSorter:
    """Provides functionality to topologically sort a graph of hashable nodes"""

    def __init__(self, graph=None):
        self._node2info = {}
        self._ready_nodes = None
        self._npassedout = 0
        self._nfinished = 0

        if graph is not None:
            for node, predecessors in graph.items():
                self.add(node, *predecessors)

    def _get_nodeinfo(self, node):
        if (result := self._node2info.get(node)) is None:
            self._node2info[node] = result = _NodeInfo(node)
        return result

    def add(self, node, *predecessors):
        """Add a new node and its predecessors to the graph.

        Both the *node* and all elements in *predecessors* must be hashable.

        If called multiple times with the same node argument, the set of dependencies
        will be the union of all dependencies passed in.

        It is possible to add a node with no dependencies (*predecessors* is not provided)
        as well as provide a dependency twice. If a node that has not been provided before
        is included among *predecessors* it will be automatically added to the graph with
        no predecessors of its own.

        Raises ValueError if called after "prepare".
        """
        if self._ready_nodes is not None:
            raise ValueError("Nodes cannot be added after a call to prepare()")

        # Create the node -> predecessor edges
        nodeinfo = self._get_nodeinfo(node)
        nodeinfo.npredecessors += len(predecessors)

        # Create the predecessor -> node edges
        for pred in predecessors:
            pred_info = self._get_nodeinfo(pred)
            pred_info.successors.append(node)

    def prepare(self):
        """Mark the graph as finished and check for cycles in the graph.

        If any cycle is detected, "CycleError" will be raised, but "get_ready" can
        still be used to obtain as many nodes as possible until cycles block more
        progress. After a call to this function, the graph cannot be modified and
        therefore no more nodes can be added using "add".
        """
        if self._ready_nodes is not None:
            raise ValueError("cannot prepare() more than once")

        self._ready_nodes = [
            i.node for i in self._node2info.values() if i.npredecessors == 0
        ]
        # ready_nodes is set before we look for cycles on purpose:
        # if the user wants to catch the CycleError, that's fine,
        # they can continue using the instance to grab as many
        # nodes as possible before cycles block more progress
        cycle = self._find_cycle()
        if cycle:
            raise CycleError(f"nodes are in a cycle", cycle)

    def get_ready(self):
        """Return a tuple of all the nodes that are ready.

        Initially it returns all nodes with no predecessors; once those are marked
        as processed by calling "done", further calls will return all new nodes that
        have all their predecessors already processed. Once no more progress can be made,
        empty tuples are returned.

        Raises ValueError if called without calling "prepare" previously.
        """
        if self._ready_nodes is None:
            raise ValueError("prepare() must be called first")

        # Get the nodes that are ready and mark them
        result = tuple(self._ready_nodes)
        n2i = self._node2info
        for node in result:
            n2i[node].npredecessors = _NODE_OUT

        # Clean the list of nodes that are ready and update
        # the counter of nodes that we have returned.
        self._ready_nodes.clear()
        self._npassedout += len(result)

        return result

    def is_active(self):
        """Return ``True`` if more progress can be made and ``False`` otherwise.

        Progress can be made if cycles do not block the resolution and either there
        are still nodes ready that haven't yet been returned by "get_ready" or the
        number of nodes marked "done" is less than the number that have been returned
        by "get_ready".

        Raises ValueError if called without calling "prepare" previously.
        """
        if self._ready_nodes is None:
            raise ValueError("prepare() must be called first")
        return self._nfinished < self._npassedout or bool(self._ready_nodes)

    def __bool__(self):
        return self.is_active()

    def done(self, *nodes):
        """Marks a set of nodes returned by "get_ready" as processed.

        This method unblocks any successor of each node in *nodes* for being returned
        in the future by a call to "get_ready".

        Raises ValueError if any node in *nodes* has already been marked as
        processed by a previous call to this method, if a node was not added to the
        graph by using "add" or if called without calling "prepare" previously or if
        node has not yet been returned by "get_ready".
        """

        if self._ready_nodes is None:
            raise ValueError("prepare() must be called first")

        n2i = self._node2info

        for node in nodes:

            # Check if we know about this node (it was added previously using add()
            if (nodeinfo := n2i.get(node)) is None:
                raise ValueError(f"node {node!r} was not added using add()")

            # If the node has not being returned (marked as ready) previously, inform the user.
            stat = nodeinfo.npredecessors
            if stat != _NODE_OUT:
                if stat >= 0:
                    raise ValueError(
                        f"node {node!r} was not passed out (still not ready)"
                    )
                elif stat == _NODE_DONE:
                    raise ValueError(f"node {node!r} was already marked done")
                else:
                    assert False, f"node {node!r}: unknown status {stat}"

            # Mark the node as processed
            nodeinfo.npredecessors = _NODE_DONE

            # Go to all the successors and reduce the number of predecessors, collecting all the ones
            # that are ready to be returned in the next get_ready() call.
            for successor in nodeinfo.successors:
                successor_info = n2i[successor]
                successor_info.npredecessors -= 1
                if successor_info.npredecessors == 0:
                    self._ready_nodes.append(successor)
            self._nfinished += 1

    def _find_cycle(self):
        n2i = self._node2info
        stack = []
        itstack = []
        seen = set()
        node2stacki = {}

        for node in n2i:
            if node in seen:
                continue

            while True:
                if node in seen:
                    # If we have seen already the node and is in the
                    # current stack we have found a cycle.
                    if node in node2stacki:
                        return stack[node2stacki[node] :] + [node]
                    # else go on to get next successor
                else:
                    seen.add(node)
                    itstack.append(iter(n2i[node].successors).__next__)
                    node2stacki[node] = len(stack)
                    stack.append(node)

                # Backtrack to the topmost stack entry with
                # at least another successor.
                while stack:
                    try:
                        node = itstack[-1]()
                        break
                    except StopIteration:
                        del node2stacki[stack.pop()]
                        itstack.pop()
                else:
                    break
        return None

    def static_order(self):
        """Returns an iterable of nodes in a topological order.

        The particular order that is returned may depend on the specific
        order in which the items were inserted in the graph.

        Using this method does not require to call "prepare" or "done". If any
        cycle is detected, :exc:`CycleError` will be raised.
        """
        self.prepare()
        while self.is_active():
            node_group = self.get_ready()
            yield from node_group
            self.done(*node_group)

    __class_getitem__ = classmethod(GenericAlias)

# ======================================================================
# Assertion helpers
# ======================================================================

# Assertion helpers (replacing unittest.TestCase methods)
def assertEqual(a, b, msg=None):
    if a != b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b))

def assertNotEqual(a, b, msg=None):
    if a == b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b))

def assertAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) > 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " != " + str(b) + " within " + str(places) + " places")

def assertNotAlmostEqual(a, b, places=7, msg=None):
    if abs(a - b) <= 0.5 * 10.0 ** (-places):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " == " + str(b) + " within " + str(places) + " places")

def assertTrue(x, msg=None):
    if not x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected True, got " + str(x))

def assertFalse(x, msg=None):
    if x:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("expected False, got " + str(x))

def assertIs(a, b, msg=None):
    if a is not b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not " + str(b))

def assertIsNot(a, b, msg=None):
    if a is b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is " + str(b))

def assertIsNone(x, msg=None):
    if x is not None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(x) + " is not None")

def assertIsNotNone(x, msg=None):
    if x is None:
        if msg:
            raise AssertionError(msg)
        raise AssertionError("unexpected None")

def assertIn(a, b, msg=None):
    if a not in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not in " + str(b))

def assertNotIn(a, b, msg=None):
    if a in b:
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " in " + str(b))

def assertIsInstance(a, b, msg=None):
    if not isinstance(a, b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " is not instance of " + str(b))

def assertGreater(a, b, msg=None):
    if not (a > b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not greater than " + str(b))

def assertGreaterEqual(a, b, msg=None):
    if not (a >= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not >= " + str(b))

def assertLess(a, b, msg=None):
    if not (a < b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not less than " + str(b))

def assertLessEqual(a, b, msg=None):
    if not (a <= b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError(str(a) + " not <= " + str(b))

def assertSequenceEqual(a, b, msg=None):
    if len(a) != len(b):
        if msg:
            raise AssertionError(msg)
        raise AssertionError("sequences differ in length: " + str(len(a)) + " vs " + str(len(b)))
    for i in range(len(a)):
        if a[i] != b[i]:
            if msg:
                raise AssertionError(msg)
            raise AssertionError("sequences differ at index " + str(i) + ": " + str(a[i]) + " != " + str(b[i]))

def assertListEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)

def assertTupleEqual(a, b, msg=None):
    assertSequenceEqual(a, b, msg)


# ======================================================================
# Test functions (extracted from CPython test suite)
# ======================================================================

# Helper methods from TestTopologicalSort
def _test_graph(graph, expected):

    def static_order_with_groups(ts):
        ts.prepare()
        while ts.is_active():
            nodes = ts.get_ready()
            for node in nodes:
                ts.done(node)
            yield tuple(sorted(nodes))
    ts = TopologicalSorter(graph)
    assertEqual(list(static_order_with_groups(ts)), list(expected))
    ts = TopologicalSorter(graph)
    it = iter(ts.static_order())
    for group in expected:
        tsgroup = {next(it) for element in group}
        assertEqual(set(group), tsgroup)

def _assert_cycle(graph, cycle):
    ts = TopologicalSorter()
    for node, dependson in graph.items():
        ts.add(node, *dependson)
    try:
        ts.prepare()
    except CycleError as e:
        _, seq = e.args
        assertIn(' '.join(map(str, cycle)), ' '.join(map(str, seq * 2)))
    else:
        raise

# Test functions from TestTopologicalSort
def TestTopologicalSort__test_simple_cases():
    _test_graph({2: {11}, 9: {11, 8}, 10: {11, 3}, 11: {7, 5}, 8: {7, 3}}, [(3, 5, 7), (8, 11), (2, 9, 10)])
    _test_graph({1: {}}, [(1,)])
    _test_graph({x: {x + 1} for x in range(10)}, [(x,) for x in range(10, -1, -1)])
    _test_graph({2: {3}, 3: {4}, 4: {5}, 5: {1}, 11: {12}, 12: {13}, 13: {14}, 14: {15}}, [(1, 15), (5, 14), (4, 13), (3, 12), (2, 11)])
    _test_graph({0: [1, 2], 1: [3], 2: [5, 6], 3: [4], 4: [9], 5: [3], 6: [7], 7: [8], 8: [4], 9: []}, [(9,), (4,), (3, 8), (1, 5, 7), (6,), (2,), (0,)])
    _test_graph({0: [1, 2], 1: [], 2: [3], 3: []}, [(1, 3), (2,), (0,)])
    _test_graph({0: [1, 2], 1: [], 2: [3], 3: [], 4: [5], 5: [6], 6: []}, [(1, 3, 6), (2, 5), (0, 4)])

def TestTopologicalSort__test_no_dependencies():
    _test_graph({1: {2}, 3: {4}, 5: {6}}, [(2, 4, 6), (1, 3, 5)])
    _test_graph({1: set(), 3: set(), 5: set()}, [(1, 3, 5)])

def TestTopologicalSort__test_the_node_multiple_times():
    _test_graph({1: {2}, 3: {4}, 0: [2, 4, 4, 4, 4, 4]}, [(2, 4), (0, 1, 3)])
    ts = TopologicalSorter()
    ts.add(1, 2)
    ts.add(1, 2)
    ts.add(1, 2)
    assertEqual([*ts.static_order()], [2, 1])

def TestTopologicalSort__test_graph_with_iterables():
    dependson = (2 * x + 1 for x in range(5))
    ts = TopologicalSorter({0: dependson})
    assertEqual(list(ts.static_order()), [1, 3, 5, 7, 9, 0])

def TestTopologicalSort__test_add_dependencies_for_same_node_incrementally():
    ts = TopologicalSorter()
    ts.add(1, 2)
    ts.add(1, 3)
    ts.add(1, 4)
    ts.add(1, 5)
    ts2 = TopologicalSorter({1: {2, 3, 4, 5}})
    assertEqual([*ts.static_order()], [*ts2.static_order()])

def TestTopologicalSort__test_empty():
    _test_graph({}, [])

def TestTopologicalSort__test_cycle():
    _assert_cycle({1: {1}}, [1, 1])
    _assert_cycle({1: {2}, 2: {1}}, [1, 2, 1])
    _assert_cycle({1: {2}, 2: {3}, 3: {1}}, [1, 3, 2, 1])
    _assert_cycle({1: {2}, 2: {3}, 3: {1}, 5: {4}, 4: {6}}, [1, 3, 2, 1])
    _assert_cycle({1: {2}, 2: {1}, 3: {4}, 4: {5}, 6: {7}, 7: {6}}, [1, 2, 1])
    _assert_cycle({1: {2}, 2: {3}, 3: {2, 4}, 4: {5}}, [3, 2])

def TestTopologicalSort__test_done():
    ts = TopologicalSorter()
    ts.add(1, 2, 3, 4)
    ts.add(2, 3)
    ts.prepare()
    assertEqual(ts.get_ready(), (3, 4))
    assertEqual(ts.get_ready(), ())
    ts.done(3)
    assertEqual(ts.get_ready(), (2,))
    assertEqual(ts.get_ready(), ())
    ts.done(4)
    ts.done(2)
    assertEqual(ts.get_ready(), (1,))
    assertEqual(ts.get_ready(), ())
    ts.done(1)
    assertEqual(ts.get_ready(), ())
    assertFalse(ts.is_active())

def TestTopologicalSort__test_is_active():
    ts = TopologicalSorter()
    ts.add(1, 2)
    ts.prepare()
    assertTrue(ts.is_active())
    assertEqual(ts.get_ready(), (2,))
    assertTrue(ts.is_active())
    ts.done(2)
    assertTrue(ts.is_active())
    assertEqual(ts.get_ready(), (1,))
    assertTrue(ts.is_active())
    ts.done(1)
    assertFalse(ts.is_active())

def TestTopologicalSort__test_order_of_insertion_does_not_matter_between_groups():

    def get_groups(ts):
        ts.prepare()
        while ts.is_active():
            nodes = ts.get_ready()
            ts.done(*nodes)
            yield set(nodes)
    ts = TopologicalSorter()
    ts.add(3, 2, 1)
    ts.add(1, 0)
    ts.add(4, 5)
    ts.add(6, 7)
    ts.add(4, 7)
    ts2 = TopologicalSorter()
    ts2.add(1, 0)
    ts2.add(3, 2, 1)
    ts2.add(4, 7)
    ts2.add(6, 7)
    ts2.add(4, 5)
    assertEqual(list(get_groups(ts)), list(get_groups(ts2)))


# ======================================================================
# Direct invocation
# ======================================================================

try:
    TestTopologicalSort__test_simple_cases()
    print("TestTopologicalSort.test_simple_cases: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_simple_cases: FAIL -", _e)
try:
    TestTopologicalSort__test_no_dependencies()
    print("TestTopologicalSort.test_no_dependencies: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_no_dependencies: FAIL -", _e)
try:
    TestTopologicalSort__test_the_node_multiple_times()
    print("TestTopologicalSort.test_the_node_multiple_times: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_the_node_multiple_times: FAIL -", _e)
try:
    TestTopologicalSort__test_graph_with_iterables()
    print("TestTopologicalSort.test_graph_with_iterables: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_graph_with_iterables: FAIL -", _e)
try:
    TestTopologicalSort__test_add_dependencies_for_same_node_incrementally()
    print("TestTopologicalSort.test_add_dependencies_for_same_node_incrementally: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_add_dependencies_for_same_node_incrementally: FAIL -", _e)
try:
    TestTopologicalSort__test_empty()
    print("TestTopologicalSort.test_empty: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_empty: FAIL -", _e)
try:
    TestTopologicalSort__test_cycle()
    print("TestTopologicalSort.test_cycle: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_cycle: FAIL -", _e)
try:
    TestTopologicalSort__test_done()
    print("TestTopologicalSort.test_done: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_done: FAIL -", _e)
try:
    TestTopologicalSort__test_is_active()
    print("TestTopologicalSort.test_is_active: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_is_active: FAIL -", _e)
try:
    TestTopologicalSort__test_order_of_insertion_does_not_matter_between_groups()
    print("TestTopologicalSort.test_order_of_insertion_does_not_matter_between_groups: PASS")
except Exception as _e:
    print("TestTopologicalSort.test_order_of_insertion_does_not_matter_between_groups: FAIL -", _e)