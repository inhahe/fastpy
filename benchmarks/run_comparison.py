"""
fastpy vs C++ vs CPython benchmark comparison.

Writes Python programs, their C++ equivalents, compiles both through
fastpy and MSVC, then times all three and produces a report.
"""
import subprocess, sys, os, time, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from compiler.pipeline import compile_source
from benchmarks.compile_cpp import compile_cpp

TMPDIR = tempfile.mkdtemp(prefix="fastpy_bench_")

# -- Benchmark definitions -------------------------------------------
# Each entry: (name, category, python_src, cpp_src)

BENCHMARKS = []

def bench(name, category, py, cpp):
    BENCHMARKS.append((name, category, py.strip(), cpp.strip()))

# ═══════════════════════════════════════════════════════════════════
# Category 1: COMMON PATTERNS  (things most programs do)
# ═══════════════════════════════════════════════════════════════════

bench("tight int loop 10M", "common", """
total = 0
i = 0
while i < 10000000:
    total = total + i
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
int main() {
    int64_t total = 0;
    for (int64_t i = 0; i < 10000000; i++)
        total += i;
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("float math loop 1M", "common", """
total = 0.0
i = 0
while i < 1000000:
    total = total + i * 0.5 + 1.0
    i = i + 1
print(total)
""", """
#include <stdio.h>
int main() {
    double total = 0.0;
    for (int i = 0; i < 1000000; i++)
        total += i * 0.5 + 1.0;
    printf("%g\\n", total);
    return 0;
}
""")

bench("recursive fib(35)", "common", """
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
print(fib(35))
""", """
#include <stdio.h>
#include <stdint.h>
int64_t fib(int64_t n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}
int main() {
    printf("%lld\\n", (long long)fib(35));
    return 0;
}
""")

bench("function calls 10M", "common", """
def add(a, b):
    return a + b
total = 0
i = 0
while i < 10000000:
    total = total + add(i, 1)
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
__declspec(noinline) int64_t add(int64_t a, int64_t b) { return a + b; }
int main() {
    int64_t total = 0;
    for (int64_t i = 0; i < 10000000; i++)
        total += add(i, 1);
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("list build+sum 100K", "common", """
lst = []
i = 0
while i < 100000:
    lst.append(i)
    i = i + 1
total = 0
for x in lst:
    total = total + x
print(total)
""", """
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
int main() {
    int64_t *lst = (int64_t*)malloc(100000 * sizeof(int64_t));
    for (int i = 0; i < 100000; i++) lst[i] = i;
    int64_t total = 0;
    for (int i = 0; i < 100000; i++) total += lst[i];
    printf("%lld\\n", (long long)total);
    free(lst);
    return 0;
}
""")

bench("dict lookup 1K keys x 1K", "common", """
d = {}
i = 0
while i < 1000:
    d[i] = i * i
    i = i + 1
total = 0
j = 0
while j < 1000:
    i = 0
    while i < 1000:
        total = total + d[i]
        i = i + 1
    j = j + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
#include <unordered_map>
int main() {
    std::unordered_map<int64_t, int64_t> d;
    for (int64_t i = 0; i < 1000; i++) d[i] = i * i;
    int64_t total = 0;
    for (int j = 0; j < 1000; j++)
        for (int64_t i = 0; i < 1000; i++)
            total += d[i];
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("string concat 100K", "common", """
parts = []
i = 0
while i < 100000:
    parts.append("x")
    i = i + 1
result = "".join(parts)
print(len(result))
""", """
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
int main() {
    char *result = (char*)malloc(100001);
    memset(result, 'x', 100000);
    result[100000] = 0;
    printf("%d\\n", (int)strlen(result));
    free(result);
    return 0;
}
""")

# ═══════════════════════════════════════════════════════════════════
# Category 2: CLASS/OOP PATTERNS  (attribute access, methods)
# ═══════════════════════════════════════════════════════════════════

bench("attr access 10M", "class-heavy", """
class Pair:
    def __init__(self, x, y):
        self.x = x
        self.y = y
p = Pair(3, 4)
total = 0
i = 0
while i < 10000000:
    total = total + p.x + p.y
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
struct Pair { int64_t x, y; };
int main() {
    Pair p = {3, 4};
    int64_t total = 0;
    for (int i = 0; i < 10000000; i++)
        total += p.x + p.y;
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("method call 1M", "class-heavy", """
class Calc:
    def __init__(self, base):
        self.base = base
    def compute(self, x):
        return self.base + x * 2
c = Calc(100)
total = 0
i = 0
while i < 1000000:
    total = total + c.compute(i)
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
struct Calc {
    int64_t base;
    int64_t compute(int64_t x) { return base + x * 2; }
};
int main() {
    Calc c = {100};
    int64_t total = 0;
    for (int64_t i = 0; i < 1000000; i++)
        total += c.compute(i);
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("dist_sq method 1M", "class-heavy", """
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def dist_sq(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy
p1 = Point(3, 4)
p2 = Point(7, 1)
total = 0
i = 0
while i < 1000000:
    total = total + p1.dist_sq(p2)
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
struct Point {
    int64_t x, y;
    int64_t dist_sq(const Point& o) const {
        int64_t dx = x - o.x, dy = y - o.y;
        return dx*dx + dy*dy;
    }
};
int main() {
    Point p1 = {3, 4}, p2 = {7, 1};
    int64_t total = 0;
    for (int i = 0; i < 1000000; i++)
        total += p1.dist_sq(p2);
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("object creation 100K", "class-heavy", """
class Node:
    def __init__(self, val):
        self.val = val
        self.next = None
lst = []
i = 0
while i < 100000:
    lst.append(Node(i))
    i = i + 1
total = 0
for n in lst:
    total = total + n.val
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
#include <vector>
struct Node { int64_t val; Node* next; };
int main() {
    std::vector<Node*> lst;
    lst.reserve(100000);
    for (int i = 0; i < 100000; i++) {
        Node* n = new Node();
        n->val = i; n->next = nullptr;
        lst.push_back(n);
    }
    int64_t total = 0;
    for (auto n : lst) total += n->val;
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("inheritance + polymorphism", "class-heavy", """
class Shape:
    def area(self):
        return 0
class Circle(Shape):
    def __init__(self, r):
        self.r = r
    def area(self):
        return self.r * self.r * 3
class Rect(Shape):
    def __init__(self, w, h):
        self.w = w
        self.h = h
    def area(self):
        return self.w * self.h
shapes = []
i = 0
while i < 100000:
    if i % 2 == 0:
        shapes.append(Circle(i))
    else:
        shapes.append(Rect(i, i + 1))
    i = i + 1
total = 0
for s in shapes:
    total = total + s.area()
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
#include <vector>
struct Shape { virtual int64_t area() { return 0; } virtual ~Shape() {} };
struct Circle : Shape { int64_t r; Circle(int64_t r) : r(r) {} int64_t area() override { return r*r*3; } };
struct Rect : Shape { int64_t w, h; Rect(int64_t w, int64_t h) : w(w), h(h) {} int64_t area() override { return w*h; } };
int main() {
    std::vector<Shape*> shapes;
    shapes.reserve(100000);
    for (int64_t i = 0; i < 100000; i++) {
        if (i % 2 == 0) shapes.push_back(new Circle(i));
        else shapes.push_back(new Rect(i, i+1));
    }
    int64_t total = 0;
    for (auto s : shapes) total += s->area();
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

# ═══════════════════════════════════════════════════════════════════
# Category 3: LESS COMMON / SLOWER PATTERNS
# ═══════════════════════════════════════════════════════════════════

bench("linked list traverse 100K", "less-common", """
class Node:
    def __init__(self, val):
        self.val = val
        self.next = None
head = Node(0)
cur = head
i = 1
while i < 100000:
    n = Node(i)
    cur.next = n
    cur = n
    i = i + 1
total = 0
cur = head
while cur is not None:
    total = total + cur.val
    cur = cur.next
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
struct Node { int64_t val; Node* next; };
int main() {
    Node* head = new Node{0, nullptr};
    Node* cur = head;
    for (int64_t i = 1; i < 100000; i++) {
        Node* n = new Node{i, nullptr};
        cur->next = n;
        cur = n;
    }
    int64_t total = 0;
    for (Node* c = head; c; c = c->next) total += c->val;
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("recursive tree sum", "less-common", """
class Tree:
    def __init__(self, val, left, right):
        self.val = val
        self.left = left
        self.right = right

def tree_sum(t):
    if t is None:
        return 0
    return t.val + tree_sum(t.left) + tree_sum(t.right)

root = Tree(1, Tree(2, Tree(3, None, None), Tree(4, None, None)), Tree(5, Tree(6, None, None), Tree(7, None, None)))
total = 0
i = 0
while i < 100000:
    total = total + tree_sum(root)
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
struct Tree { int64_t val; Tree *left, *right; };
int64_t tree_sum(Tree* t) {
    if (!t) return 0;
    return t->val + tree_sum(t->left) + tree_sum(t->right);
}
int main() {
    Tree n3={3,0,0}, n4={4,0,0}, n6={6,0,0}, n7={7,0,0};
    Tree n2={2,&n3,&n4}, n5={5,&n6,&n7};
    Tree root={1,&n2,&n5};
    int64_t total = 0;
    for (int i = 0; i < 100000; i++) total += tree_sum(&root);
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("exception handling 100K", "less-common", """
def safe_div(a, b):
    try:
        return a // b
    except ZeroDivisionError:
        return 0
total = 0
i = 0
while i < 100000:
    total = total + safe_div(i, 3)
    i = i + 1
print(total)
""", """
#include <stdio.h>
#include <stdint.h>
int64_t safe_div(int64_t a, int64_t b) {
    if (b == 0) return 0;
    return a / b;
}
int main() {
    int64_t total = 0;
    for (int64_t i = 0; i < 100000; i++)
        total += safe_div(i, 3);
    printf("%lld\\n", (long long)total);
    return 0;
}
""")

bench("list comprehension + filter", "less-common", """
data = [i * i for i in range(100000)]
result = [x for x in data if x % 3 == 0]
print(len(result))
""", """
#include <stdio.h>
#include <stdint.h>
#include <vector>
int main() {
    std::vector<int64_t> data(100000), result;
    for (int64_t i = 0; i < 100000; i++) data[i] = i * i;
    for (auto x : data) if (x % 3 == 0) result.push_back(x);
    printf("%lld\\n", (long long)result.size());
    return 0;
}
""")

# -- Runner ----------------------------------------------------------

def time_exe(exe_path, runs=3, timeout=60):
    """Run an executable and return best time in ms."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        out = subprocess.run([str(exe_path)], capture_output=True, text=True, timeout=timeout)
        t1 = time.perf_counter()
        if out.returncode != 0:
            return None, out.stderr[:100]
        times.append((t1 - t0) * 1000)
    return min(times), None

def time_cpython(src, runs=3, timeout=60):
    """Run Python source under CPython and return best time in ms."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        out = subprocess.run([sys.executable, '-c', src], capture_output=True, text=True, timeout=timeout)
        t1 = time.perf_counter()
        if out.returncode != 0:
            return None, out.stderr[:100]
        times.append((t1 - t0) * 1000)
    return min(times), None

def main():
    results = []

    for name, category, py_src, cpp_src in BENCHMARKS:
        print(f"  {name}...", end=" ", flush=True)

        # Compile fastpy
        r = compile_source(py_src)
        if not r.success:
            print("SKIP (compile fail)")
            results.append((name, category, None, None, None))
            continue
        fp_ms, fp_err = time_exe(r.executable)

        # Compile C++
        cpp_file = os.path.join(TMPDIR, f"{name.replace(' ', '_')}.cpp")
        cpp_exe = os.path.join(TMPDIR, f"{name.replace(' ', '_')}.exe")
        with open(cpp_file, 'w') as f:
            f.write(cpp_src)
        if not compile_cpp(cpp_file, cpp_exe):
            print("SKIP (C++ compile fail)")
            results.append((name, category, fp_ms, None, None))
            continue
        cpp_ms, cpp_err = time_exe(cpp_exe)

        # CPython
        cp_ms, cp_err = time_cpython(py_src)

        if fp_ms and cpp_ms and cp_ms:
            print(f"fastpy={fp_ms:.0f}ms  C++={cpp_ms:.0f}ms  CPython={cp_ms:.0f}ms")
        else:
            print(f"fp={fp_ms} cpp={cpp_ms} cp={cp_ms}")

        results.append((name, category, fp_ms, cpp_ms, cp_ms))

    # -- Report ------------------------------------------------------
    print("\n" + "=" * 85)
    print("FASTPY vs C++ vs CPython BENCHMARK REPORT")
    print("=" * 85)

    STARTUP = 7  # fastpy subprocess startup overhead (ms)
    CPP_STARTUP = 1  # C++ subprocess startup

    categories = ["common", "class-heavy", "less-common"]
    cat_labels = {
        "common": "COMMON PATTERNS (loops, functions, containers)",
        "class-heavy": "CLASS/OOP PATTERNS (attributes, methods, inheritance)",
        "less-common": "LESS COMMON / SLOWER PATTERNS (linked lists, trees, exceptions)",
    }

    for cat in categories:
        cat_results = [(n, fp, cpp, cp) for n, c, fp, cpp, cp in results if c == cat]
        if not cat_results:
            continue
        print(f"\n{'-' * 85}")
        print(f"  {cat_labels[cat]}")
        print(f"{'-' * 85}")
        print(f"  {'Benchmark':<30s} {'fastpy':>8s} {'C++':>8s} {'CPython':>8s}  {'fp/C++':>7s}  {'fp/CPy':>7s}")
        print(f"  {'':-<30s} {'':->8s} {'':->8s} {'':->8s}  {'':->7s}  {'':->7s}")

        for name, fp, cpp, cp in cat_results:
            if fp is None or cpp is None or cp is None:
                print(f"  {name:<30s}    SKIP")
                continue
            fp_compute = max(fp - STARTUP, 0.1)
            cpp_compute = max(cpp - CPP_STARTUP, 0.1)
            ratio_cpp = fp_compute / cpp_compute
            ratio_cp = cp / fp if fp > 0 else 0
            print(f"  {name:<30s} {fp:7.0f}ms {cpp:7.0f}ms {cp:7.0f}ms  {ratio_cpp:6.1f}x  {ratio_cp:6.0f}x")

    print(f"\n{'=' * 85}")
    print("Notes:")
    print("  - fastpy times include ~7ms subprocess startup overhead")
    print("  - C++ times include ~1ms subprocess startup overhead")
    print("  - fp/C++ ratio: compute-only (startup subtracted). <2x = near C++ speed")
    print("  - fp/CPy ratio: wall-clock speedup vs CPython (higher = better)")
    print(f"{'=' * 85}")

if __name__ == "__main__":
    main()
