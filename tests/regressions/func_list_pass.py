# Regression: passing a list from one function to another caused segfault.
# Bug: CSA _csa_build_var_types only scanned module-level assignments,
#   so function-local variables (e.g. a = [1,2,3] inside make_list())
#   were typed as None.  The callee's parameter defaulted to "int" tag,
#   and subscript/len went through the CPython bridge — treating the
#   native FpyList* pointer as a PyObject*, causing a segfault.
# Fix: Added per-function-scope local variable type tracking in
#   _csa_scan_and_merge so call-site arguments are correctly typed.

# 1. Basic: pass list to function, subscript + len
def get_first(lst):
    return lst[0]

def get_len(lst):
    return len(lst)

def make_and_pass():
    a = [10, 20, 30]
    print(get_first(a))
    print(get_len(a))

make_and_pass()

# 2. Pass list of objects between functions
class Pt:
    def __init__(self, x, y):
        self.x = x
        self.y = y

def max_x(points):
    best = points[0]
    i = 1
    while i < len(points):
        if points[i].x > best.x:
            best = points[i]
        i += 1
    return best

def build_and_find():
    pts = [Pt(1, 2), Pt(5, 3), Pt(3, 7)]
    m = max_x(pts)
    print(m.x)
    print(m.y)

build_and_find()

# 3. Nested function calls: create list, pass to helper, helper passes on
def sum_list(lst):
    total = 0
    i = 0
    while i < len(lst):
        total = total + lst[i]
        i += 1
    return total

def double_sum(lst):
    return sum_list(lst) * 2

def outer():
    nums = [1, 2, 3, 4, 5]
    print(double_sum(nums))

outer()

# 4. Pass dict created in function
def lookup(d, key):
    return d[key]

def test_dict():
    m = {"x": 10, "y": 20}
    print(lookup(m, "x"))
    print(lookup(m, "y"))

test_dict()

# 5. For-each over list parameter
def print_all(items):
    for x in items:
        print(x)

def test_foreach():
    data = [100, 200, 300]
    print_all(data)

test_foreach()
