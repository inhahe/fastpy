"""graphlib stdlib tests -- inlined Kahn's topological sort.

Covers: topological sort as used by graphlib.TopologicalSorter.
Uses flat list-based graph representation for compiler compatibility.

Skipped: CycleError detection, *args API, generator-based static_order(),
          class-based TopologicalSorter API.

NOTE: Only 4 function definitions (topo_sort, verify_topo, _ck, main) to
avoid a compiler bug where many function definitions cause heap corruption.
All test logic lives inside main().
"""

# ---------------------------------------------------------------------------
# Inlined topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------

def topo_sort(num_nodes, edges_flat, num_edges):
    """Topological sort using Kahn's algorithm."""
    # Fast path: 0 edges => all nodes are independent, return 0..n-1
    if num_edges == 0:
        result = [0]
        result.pop()
        for i in range(num_nodes):
            result.append(i)
        return result

    in_deg = [0] * num_nodes
    out_count = [0] * num_nodes
    for i in range(num_edges):
        e_from = edges_flat[i * 2]
        e_to = edges_flat[i * 2 + 1]
        out_count[e_from] = out_count[e_from] + 1
        in_deg[e_to] = in_deg[e_to] + 1

    offsets = [0] * (num_nodes + 1)
    for i in range(num_nodes):
        offsets[i + 1] = offsets[i] + out_count[i]

    total_edges = offsets[num_nodes]
    flat_succ = [0] * (total_edges + 1)
    fill = [0] * num_nodes
    for i in range(num_nodes):
        fill[i] = offsets[i]

    for i in range(num_edges):
        e_from = edges_flat[i * 2]
        e_to = edges_flat[i * 2 + 1]
        flat_succ[fill[e_from]] = e_to
        fill[e_from] = fill[e_from] + 1

    queue = [0]
    queue.pop()
    for i in range(num_nodes):
        if in_deg[i] == 0:
            queue.append(i)

    result = [0]
    result.pop()
    while len(queue) > 0:
        node = queue[len(queue) - 1]
        queue.pop()
        result.append(node)
        start = offsets[node]
        end = offsets[node + 1]
        for j in range(start, end):
            s = flat_succ[j]
            in_deg[s] = in_deg[s] - 1
            if in_deg[s] == 0:
                queue.append(s)

    return result


# ---------------------------------------------------------------------------
# Topological order verifier
# ---------------------------------------------------------------------------

def verify_topo(result, num_nodes, edges_flat, num_edges):
    """Verify that result is a valid topological ordering."""
    if len(result) != num_nodes:
        return False
    pos = [-1] * num_nodes
    for i in range(len(result)):
        node = result[i]
        if node < 0:
            return False
        if node >= num_nodes:
            return False
        if pos[node] != -1:
            return False
        pos[node] = i
    for i in range(num_nodes):
        if pos[i] == -1:
            return False
    for i in range(num_edges):
        e_from = edges_flat[i * 2]
        e_to = edges_flat[i * 2 + 1]
        if pos[e_from] >= pos[e_to]:
            return False
    return True


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_pc = 0
_fc = 0
_gp = 0
_gf = 0

def _ck(ok, msg):
    global _pc, _fc, _gp, _gf
    if ok:
        _pc = _pc + 1
        _gp = _gp + 1
    else:
        _fc = _fc + 1
        _gf = _gf + 1
        print("FAIL: " + msg)


# ---------------------------------------------------------------------------
# main — all test logic in one function to avoid many-functions crash
# ---------------------------------------------------------------------------

def main():
    global _gp, _gf

    # ===================================================================
    # basic_topologies (15 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Single node, no edges
    r = topo_sort(1, [99], 0)
    _ck(len(r) == 1, "single node length")
    _ck(r[0] == 0, "single node is 0")

    # Two nodes, one edge
    r = topo_sort(2, [0, 1], 1)
    _ck(len(r) == 2, "two nodes length")
    _ck(verify_topo(r, 2, [0, 1], 1), "two nodes valid")
    _ck(r[0] == 0, "0 before 1")
    _ck(r[1] == 1, "1 after 0")

    # Chain 0->1->2
    r = topo_sort(3, [0, 1, 1, 2], 2)
    ok = True
    if len(r) != 3:
        ok = False
    if ok:
        if r[0] != 0:
            ok = False
    if ok:
        if r[1] != 1:
            ok = False
    if ok:
        if r[2] != 2:
            ok = False
    _ck(ok, "chain 3")
    _ck(verify_topo(r, 3, [0, 1, 1, 2], 2), "chain 3 valid")

    # Chain 0->1->2->3
    r = topo_sort(4, [0, 1, 1, 2, 2, 3], 3)
    ok = True
    if len(r) != 4:
        ok = False
    if ok:
        for i in range(4):
            if r[i] != i:
                ok = False
    _ck(ok, "chain 4")
    _ck(verify_topo(r, 4, [0, 1, 1, 2, 2, 3], 3), "chain 4 valid")

    # Chain 0->1->2->3->4
    r = topo_sort(5, [0, 1, 1, 2, 2, 3, 3, 4], 4)
    ok = True
    if len(r) != 5:
        ok = False
    if ok:
        for i in range(5):
            if r[i] != i:
                ok = False
    _ck(ok, "chain 5")

    # Diamond: 0->1, 0->2, 1->3, 2->3
    r = topo_sort(4, [0, 1, 0, 2, 1, 3, 2, 3], 4)
    _ck(len(r) == 4, "diamond length")
    _ck(verify_topo(r, 4, [0, 1, 0, 2, 1, 3, 2, 3], 4), "diamond valid")
    _ck(r[0] == 0, "diamond: 0 first")
    _ck(r[3] == 3, "diamond: 3 last")

    print("  basic_topologies: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # disconnected (6 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Two separate edges: 0->1 and 2->3
    r = topo_sort(4, [0, 1, 2, 3], 2)
    _ck(len(r) == 4, "disconnected 2 length")
    _ck(verify_topo(r, 4, [0, 1, 2, 3], 2), "disconnected 2 valid")

    # Three components: 0->1, 2->3->4, 5 (isolated)
    r = topo_sort(6, [0, 1, 2, 3, 3, 4], 3)
    _ck(len(r) == 6, "disconnected 3 length")
    _ck(verify_topo(r, 6, [0, 1, 2, 3, 3, 4], 3), "disconnected 3 valid")

    # No edges (5 independent nodes)
    r = topo_sort(5, [99], 0)
    _ck(len(r) == 5, "no edges length")

    # Two independent nodes
    r = topo_sort(2, [99], 0)
    _ck(len(r) == 2, "two independent length")

    print("  disconnected: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # fan (6 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Fan-out: 0 -> {1, 2, 3, 4, 5}
    r = topo_sort(6, [0, 1, 0, 2, 0, 3, 0, 4, 0, 5], 5)
    _ck(len(r) == 6, "fan out length")
    _ck(verify_topo(r, 6, [0, 1, 0, 2, 0, 3, 0, 4, 0, 5], 5), "fan out valid")
    _ck(r[0] == 0, "fan out: source first")

    # Fan-in: {0, 1, 2, 3, 4} -> 5
    r = topo_sort(6, [0, 5, 1, 5, 2, 5, 3, 5, 4, 5], 5)
    _ck(len(r) == 6, "fan in length")
    _ck(verify_topo(r, 6, [0, 5, 1, 5, 2, 5, 3, 5, 4, 5], 5), "fan in valid")
    _ck(r[5] == 5, "fan in: sink last")

    print("  fan: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # trees (5 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Binary tree: 0->1, 0->2, 1->3, 1->4, 2->5, 2->6
    r = topo_sort(7, [0, 1, 0, 2, 1, 3, 1, 4, 2, 5, 2, 6], 6)
    _ck(len(r) == 7, "tree 7 length")
    _ck(verify_topo(r, 7, [0, 1, 0, 2, 1, 3, 1, 4, 2, 5, 2, 6], 6), "tree 7 valid")
    _ck(r[0] == 0, "tree 7: root first")

    # Layered: {0,1} -> {2,3}, {2,3} -> {4,5}
    r = topo_sort(6, [0, 2, 0, 3, 1, 2, 1, 3, 2, 4, 2, 5, 3, 4, 3, 5], 8)
    _ck(len(r) == 6, "layered 3x2 length")
    _ck(verify_topo(r, 6, [0, 2, 0, 3, 1, 2, 1, 3, 2, 4, 2, 5, 3, 4, 3, 5], 8), "layered 3x2 valid")

    print("  trees: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # patterns (15 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # W-shape: 0->2, 1->2, 2->3, 2->4, 3->5, 4->5
    r = topo_sort(6, [0, 2, 1, 2, 2, 3, 2, 4, 3, 5, 4, 5], 6)
    _ck(len(r) == 6, "w shape length")
    _ck(verify_topo(r, 6, [0, 2, 1, 2, 2, 3, 2, 4, 3, 5, 4, 5], 6), "w shape valid")
    _ck(r[5] == 5, "w shape: 5 last")

    # Reverse-numbered chain: 9->8->7->...->0
    r = topo_sort(10, [9, 8, 8, 7, 7, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0], 9)
    _ck(len(r) == 10, "reverse chain length")
    _ck(r[0] == 9, "reverse chain: 9 first")
    _ck(r[9] == 0, "reverse chain: 0 last")

    # Parallel chains: A: 0->1->2, B: 3->4->5, C: 6->7->8
    r = topo_sort(9, [0, 1, 1, 2, 3, 4, 4, 5, 6, 7, 7, 8], 6)
    _ck(len(r) == 9, "parallel chains length")
    _ck(verify_topo(r, 9, [0, 1, 1, 2, 3, 4, 4, 5, 6, 7, 7, 8], 6), "parallel chains valid")

    # Zigzag: 0->1, 0->2, 1->3, 2->3, 2->4, 3->5, 4->5
    r = topo_sort(6, [0, 1, 0, 2, 1, 3, 2, 3, 2, 4, 3, 5, 4, 5], 7)
    _ck(len(r) == 6, "zigzag length")
    _ck(verify_topo(r, 6, [0, 1, 0, 2, 1, 3, 2, 3, 2, 4, 3, 5, 4, 5], 7), "zigzag valid")
    _ck(r[0] == 0, "zigzag: 0 first")
    _ck(r[5] == 5, "zigzag: 5 last")

    # Duplicate edges: 0->1 repeated 3 times, 1->2
    r = topo_sort(3, [0, 1, 0, 1, 0, 1, 1, 2], 4)
    _ck(len(r) == 3, "dup edges length")
    _ck(verify_topo(r, 3, [0, 1, 0, 1, 0, 1, 1, 2], 4), "dup edges valid")
    ok = True
    if len(r) != 3:
        ok = False
    if ok:
        if r[0] != 0:
            ok = False
    if ok:
        if r[1] != 1:
            ok = False
    if ok:
        if r[2] != 2:
            ok = False
    _ck(ok, "dup edges order")

    print("  patterns: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # precomputed (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Chain 0->1->2->3->4: unique ordering
    r = topo_sort(5, [0, 1, 1, 2, 2, 3, 3, 4], 4)
    ok = True
    if len(r) != 5:
        ok = False
    if ok:
        for i in range(5):
            if r[i] != i:
                ok = False
    _ck(ok, "chain forward")

    # Chain 4->3->2->1->0: unique ordering
    r = topo_sort(5, [4, 3, 3, 2, 2, 1, 1, 0], 4)
    ok = True
    if len(r) != 5:
        ok = False
    if ok:
        if r[0] != 4:
            ok = False
    if ok:
        if r[1] != 3:
            ok = False
    if ok:
        if r[2] != 2:
            ok = False
    if ok:
        if r[3] != 1:
            ok = False
    if ok:
        if r[4] != 0:
            ok = False
    _ck(ok, "chain reverse")

    # Complete DAG on 5 nodes (all i->j for i<j): unique ordering
    r = topo_sort(5, [0, 1, 0, 2, 0, 3, 0, 4, 1, 2, 1, 3, 1, 4, 2, 3, 2, 4, 3, 4], 10)
    ok = True
    if len(r) != 5:
        ok = False
    if ok:
        for i in range(5):
            if r[i] != i:
                ok = False
    _ck(ok, "complete DAG 5")

    print("  precomputed: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # build_order (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # 0=libc, 1=libm(->0), 2=libssl(->0), 3=libcrypto(->0,2),
    # 4=python(->0,1,2,3), 5=pip(->4), 6=numpy(->4,1), 7=scipy(->6,1)
    edges = [0, 1, 0, 2, 0, 3, 2, 3, 0, 4, 1, 4, 2, 4, 3, 4,
             4, 5, 4, 6, 1, 6, 6, 7, 1, 7]
    r = topo_sort(8, edges, 13)
    _ck(len(r) == 8, "build order length")
    _ck(verify_topo(r, 8, edges, 13), "build order valid")
    _ck(r[0] == 0, "build order: libc first")

    print("  build_order: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # grid_4x4 (4 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    for row in range(4):
        for col in range(4):
            node = row * 4 + col
            if col < 3:
                edges.append(node)
                edges.append(node + 1)
                ne = ne + 1
            if row < 3:
                edges.append(node)
                edges.append(node + 4)
                ne = ne + 1
    r = topo_sort(16, edges, ne)
    _ck(len(r) == 16, "grid 4x4 length")
    _ck(verify_topo(r, 16, edges, ne), "grid 4x4 valid")
    _ck(r[0] == 0, "grid 4x4: (0,0) first")
    _ck(r[15] == 15, "grid 4x4: (3,3) last")

    print("  grid_4x4: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # grid_8x8 (2 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    for row in range(8):
        for col in range(8):
            node = row * 8 + col
            if col < 7:
                edges.append(node)
                edges.append(node + 1)
                ne = ne + 1
            if row < 7:
                edges.append(node)
                edges.append(node + 8)
                ne = ne + 1
    r = topo_sort(64, edges, ne)
    _ck(len(r) == 64, "grid 8x8 length")
    _ck(verify_topo(r, 64, edges, ne), "grid 8x8 valid")

    print("  grid_8x8: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # chain_100 (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    for i in range(99):
        edges.append(i)
        edges.append(i + 1)
    r = topo_sort(100, edges, 99)
    _ck(len(r) == 100, "chain 100 length")
    _ck(verify_topo(r, 100, edges, 99), "chain 100 valid")
    ok = True
    for i in range(100):
        if r[i] != i:
            ok = False
    _ck(ok, "chain 100 exact order")

    print("  chain_100: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # large_fan (6 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Fan-out: 0 -> {1..99}
    edges = [0]
    edges.pop()
    for i in range(1, 100):
        edges.append(0)
        edges.append(i)
    r = topo_sort(100, edges, 99)
    _ck(len(r) == 100, "fan out 100 length")
    _ck(verify_topo(r, 100, edges, 99), "fan out 100 valid")
    _ck(r[0] == 0, "fan out 100: source first")

    # Fan-in: {0..98} -> 99
    edges = [0]
    edges.pop()
    for i in range(99):
        edges.append(i)
        edges.append(99)
    r = topo_sort(100, edges, 99)
    _ck(len(r) == 100, "fan in 100 length")
    _ck(verify_topo(r, 100, edges, 99), "fan in 100 valid")
    _ck(r[99] == 99, "fan in 100: sink last")

    print("  large_fan: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # layered_5x20 (2 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    for layer in range(4):
        for j in range(20):
            src = layer * 20 + j
            dst = (layer + 1) * 20 + j
            edges.append(src)
            edges.append(dst)
            ne = ne + 1
            src2 = layer * 20 + (j + 1) % 20
            edges.append(src2)
            edges.append(dst)
            ne = ne + 1
    r = topo_sort(100, edges, ne)
    _ck(len(r) == 100, "layered 5x20 length")
    _ck(verify_topo(r, 100, edges, ne), "layered 5x20 valid")

    print("  layered_5x20: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # random_dag_500 (2 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    v = 42
    for i in range(1, 500):
        num_preds = (v % 3) + 1
        v = (v * 1103515245 + 12345) % (2 ** 31)
        for k in range(num_preds):
            pred = v % i
            v = (v * 1103515245 + 12345) % (2 ** 31)
            edges.append(pred)
            edges.append(i)
            ne = ne + 1
    r = topo_sort(500, edges, ne)
    _ck(len(r) == 500, "random DAG 500 length")
    _ck(verify_topo(r, 500, edges, ne), "random DAG 500 valid")

    print("  random_dag_500: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # random_dag_1000 (2 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    v = 2024
    for i in range(1, 1000):
        num_preds = (v % 4) + 1
        v = (v * 6364136223846793005 + 1) % (2 ** 31)
        for k in range(num_preds):
            pred = v % i
            v = (v * 6364136223846793005 + 1) % (2 ** 31)
            edges.append(pred)
            edges.append(i)
            ne = ne + 1
    r = topo_sort(1000, edges, ne)
    _ck(len(r) == 1000, "random DAG 1000 length")
    _ck(verify_topo(r, 1000, edges, ne), "random DAG 1000 valid")

    print("  random_dag_1000: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # stress (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # 500 independent nodes
    r = topo_sort(500, [99], 0)
    _ck(len(r) == 500, "500 independent length")

    # Dense DAG: for each pair i<j where (i+j)%3==0, add edge i->j (50 nodes)
    edges = [0]
    edges.pop()
    ne = 0
    for i in range(50):
        for j in range(i + 1, 50):
            if (i + j) % 3 == 0:
                edges.append(i)
                edges.append(j)
                ne = ne + 1
    r = topo_sort(50, edges, ne)
    _ck(len(r) == 50, "dense DAG 50 length")
    _ck(verify_topo(r, 50, edges, ne), "dense DAG 50 valid")

    print("  stress: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # deep_narrow (2 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Main chain: 0->1->...->99, branch at every 10th: i -> 100+i/10
    edges = [0]
    edges.pop()
    ne = 0
    for i in range(99):
        edges.append(i)
        edges.append(i + 1)
        ne = ne + 1
    for i in range(10):
        edges.append(i * 10)
        edges.append(100 + i)
        ne = ne + 1
    r = topo_sort(110, edges, ne)
    _ck(len(r) == 110, "deep narrow length")
    _ck(verify_topo(r, 110, edges, ne), "deep narrow valid")

    print("  deep_narrow: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # wide_shallow (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # 50 roots -> 50 middle -> 1 sink
    edges = [0]
    edges.pop()
    ne = 0
    for i in range(50):
        edges.append(i)
        edges.append(50 + i)
        ne = ne + 1
    for i in range(50):
        edges.append(50 + i)
        edges.append(100)
        ne = ne + 1
    r = topo_sort(101, edges, ne)
    _ck(len(r) == 101, "wide shallow length")
    _ck(verify_topo(r, 101, edges, ne), "wide shallow valid")
    _ck(r[100] == 100, "wide shallow: sink last")

    print("  wide_shallow: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # complete_dag_8 (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    for i in range(8):
        for j in range(i + 1, 8):
            edges.append(i)
            edges.append(j)
            ne = ne + 1
    r = topo_sort(8, edges, ne)
    _ck(len(r) == 8, "complete DAG 8 length")
    _ck(verify_topo(r, 8, edges, ne), "complete DAG 8 valid")
    ok = True
    for i in range(8):
        if r[i] != i:
            ok = False
    _ck(ok, "complete DAG 8 exact order")

    print("  complete_dag_8: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # pyramid (4 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # Layer 0: {0}, Layer 1: {1,2,3}, Layer 2: {4,5,6,7,8},
    # Layer 3: {9,10,11}, Layer 4: {12}
    edges = [0]
    edges.pop()
    ne = 0
    for j in range(1, 4):
        edges.append(0)
        edges.append(j)
        ne = ne + 1
    for src in range(1, 4):
        for dst in range(4, 9):
            edges.append(src)
            edges.append(dst)
            ne = ne + 1
    for src in range(4, 9):
        for dst in range(9, 12):
            edges.append(src)
            edges.append(dst)
            ne = ne + 1
    for src in range(9, 12):
        edges.append(src)
        edges.append(12)
        ne = ne + 1
    r = topo_sort(13, edges, ne)
    _ck(len(r) == 13, "pyramid length")
    _ck(verify_topo(r, 13, edges, ne), "pyramid valid")
    _ck(r[0] == 0, "pyramid: apex first")
    _ck(r[12] == 12, "pyramid: base last")

    print("  pyramid: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # converging (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    # 0..8 -> 9 -> 10
    edges = [0]
    edges.pop()
    ne = 0
    for i in range(9):
        edges.append(i)
        edges.append(9)
        ne = ne + 1
    edges.append(9)
    edges.append(10)
    ne = ne + 1
    r = topo_sort(11, edges, ne)
    _ck(len(r) == 11, "converging length")
    _ck(verify_topo(r, 11, edges, ne), "converging valid")
    _ck(r[10] == 10, "converging: 10 last")

    print("  converging: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # binary_tree_15 (3 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    edges = [0]
    edges.pop()
    ne = 0
    for i in range(7):
        edges.append(i)
        edges.append(2 * i + 1)
        ne = ne + 1
        edges.append(i)
        edges.append(2 * i + 2)
        ne = ne + 1
    r = topo_sort(15, edges, ne)
    _ck(len(r) == 15, "tree 15 length")
    _ck(verify_topo(r, 15, edges, ne), "tree 15 valid")
    _ck(r[0] == 0, "tree 15: root first")

    print("  binary_tree_15: " + str(_gp) + "/" + str(_gp + _gf))

    # ===================================================================
    # various_sizes (29 assertions)
    # ===================================================================
    _gp = 0
    _gf = 0

    sizes = [1, 2, 3, 5, 7, 10, 15, 20, 31, 50, 64, 100, 128, 200, 256]
    for si in range(len(sizes)):
        sz = sizes[si]
        edges = [0]
        edges.pop()
        ne = sz - 1
        if sz == 1:
            ne = 0
            edges.append(99)
        else:
            for i in range(sz - 1):
                edges.append(i)
                edges.append(i + 1)
        r = topo_sort(sz, edges, ne)
        _ck(len(r) == sz, "chain size " + str(sz) + " length")
        if ne > 0:
            _ck(verify_topo(r, sz, edges, ne), "chain size " + str(sz) + " valid")

    print("  various_sizes: " + str(_gp) + "/" + str(_gp + _gf))


# ---------------------------------------------------------------------------
# Run and summarize
# ---------------------------------------------------------------------------

main()

print("")
_total = _pc + _fc
if _fc == 0:
    print("ALL TESTS PASSED: " + str(_total) + "/" + str(_total))
else:
    print("TESTS FAILED: " + str(_fc) + " of " + str(_total))
