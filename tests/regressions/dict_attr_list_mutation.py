# Regression: in-place mutation of lists/dicts retrieved from object
# attribute dicts via subscript.
# Bug: fpy_fv_call_method1 converted FpyList/FpyDict to PyObject* (copying
#   the data) before calling the method through CPython.  In-place mutations
#   like .append() modified the copy; the original was never touched.
# Fix: native dispatch in fpy_fv_call_method{0,1,2} — when the receiver
#   tag is LIST or DICT, call fastpy runtime functions directly instead of
#   going through the CPython bridge.

# 1. Module-level dict of lists (control — always worked)
d = {"a": [1, 2], "b": [3, 4]}
d["a"].append(99)
print(d["a"])   # [1, 2, 99]

# 2. Object attribute dict of lists — external mutation
class Holder:
    def __init__(self):
        self.d = {"x": [10], "y": [20]}

h = Holder()
h.d["x"].append(50)
print(h.d["x"])   # [10, 50]

# 3. Object attribute dict of lists — method-internal mutation
class Graph:
    def __init__(self):
        self.adj = {}

    def add_edge(self, u, v):
        if u not in self.adj:
            self.adj[u] = []
        self.adj[u].append(v)

g = Graph()
g.add_edge("a", "b")
g.add_edge("a", "c")
g.add_edge("b", "d")
print(g.adj["a"])   # ['b', 'c']
print(g.adj["b"])   # ['d']

# 4. Retrieve list from attr-dict into local, mutate local
class Holder2:
    def __init__(self):
        self.d = {"a": [1, 2]}

h2 = Holder2()
lst = h2.d["a"]
lst.append(3)
print(lst)        # [1, 2, 3]
print(h2.d["a"])  # [1, 2, 3]  — same list

# 5. Dict attr subscript store + read (control)
class Simple:
    def __init__(self):
        self.data = {}

    def set(self, k, v):
        self.data[k] = v

    def get(self, k):
        return self.data[k]

s = Simple()
s.set("hello", 42)
print(s.get("hello"))  # 42

# 6. Dict ref aliasing through attr
class Holder3:
    def __init__(self):
        self.d = {"x": 100}

h3 = Holder3()
ref = h3.d
ref["y"] = 200
print(h3.d["y"])  # 200

# 7. list.extend through FV dispatch
class Collector:
    def __init__(self):
        self.items = {}

    def add(self, key, values):
        if key not in self.items:
            self.items[key] = []
        self.items[key].extend(values)

c = Collector()
c.add("x", [1, 2])
c.add("x", [3, 4])
print(c.items["x"])  # [1, 2, 3, 4]

# 8. Nested method: self.d[k].append inside a method, print via attr access
class MultiMap:
    def __init__(self):
        self.m = {}

    def add(self, key, val):
        if key not in self.m:
            self.m[key] = []
        self.m[key].append(val)

mm = MultiMap()
mm.add("colors", "red")
mm.add("colors", "blue")
mm.add("shapes", "circle")
print(mm.m["colors"])  # ['red', 'blue']
print(mm.m["shapes"])  # ['circle']

# 9. Method returning self.attr[key] — return tag propagation
class Getter:
    def __init__(self):
        self.d = {"a": [10, 20]}

    def get(self, k):
        return self.d[k]

gt = Getter()
val = gt.get("a")
print(val)              # [10, 20]
