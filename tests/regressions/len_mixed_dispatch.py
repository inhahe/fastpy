# Regression: len() must use fv_len runtime dispatch for mixed/unknown-typed
# values. Previously crashed via cpython_len (expected PyObject*, got native ptr).

def measure(x):
    """len() on an unknown-typed parameter — called with str and list."""
    return len(x)

# Direct calls with different types
print(measure("abc"))          # 3
print(measure([1, 2, 3, 4]))  # 4

# Forwarding through another unknown-typed function
def forward(v):
    return measure(v)

print(forward("hi"))    # 2
print(forward([10]))    # 1

# len() on dict with unknown-typed param
def dict_len(d):
    return len(d)

print(dict_len({1: 'a', 2: 'b'}))  # 2
print(dict_len({'x': 1}))          # 1
