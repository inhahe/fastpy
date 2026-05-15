# Regression: CSA variable scope isolation
# Bug: _csa_build_var_types used ast.walk(tree) which walked into
# function bodies, treating function-local variables as module-level.
# When two functions shared a local variable name (e.g. "result") with
# different types (list vs int), the CSA type info got poisoned,
# causing scope-cleanup refcount corruption and segfaults.
# Fix: Use a custom walker that skips function/class bodies, so only
# true module-level assignments populate var_types.

# Case 1: Two functions sharing "result" variable name
def make_list():
    result = []
    result.append([10, 20])
    return result

def compute(n):
    if n <= 1:
        return n
    result = compute(n - 1) + compute(n - 2)
    return result

r = make_list()
print(r)             # [[10, 20]]
print(compute(6))    # 8

# Case 2: Function creates list-of-lists + memoized fib
def transpose(matrix):
    rows = len(matrix)
    cols = len(matrix[0])
    result = []
    for j in range(cols):
        row = []
        for i in range(rows):
            row.append(matrix[i][j])
        result.append(row)
    return result

m = [[1, 2, 3], [4, 5, 6]]
t = transpose(m)
print(t[0])  # [1, 4]
print(t[1])  # [2, 5]
print(t[2])  # [3, 6]

memo = {}
def fib(n):
    if n in memo:
        return memo[n]
    if n <= 1:
        return n
    result = fib(n - 1) + fib(n - 2)
    memo[n] = result
    return result

print(fib(7))  # 13

# Case 3: Mixed-type list passed to function (list:mixed CSA tag)
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            for x in item:
                result.append(x)
        else:
            result.append(item)
    return result

mixed = [1, [2, 3], [4, 5]]
print(flatten(mixed))  # [1, 2, 3, 4, 5]

# Case 4: Dict with list values passed to function (dict:list CSA tag)
graph = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}
def get_neighbors(g, node):
    result = []
    for n in g[node]:
        result.append(n)
    return result

print(get_neighbors(graph, "A"))  # ['B', 'C']
