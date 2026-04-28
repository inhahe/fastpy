# Regression: unknown-typed params should use runtime dispatch
# Tests that functions called with untyped arguments still dispatch correctly.

def get_length(item):
    """Called with both str and list — param type unknown at some call sites."""
    return len(item)

# Call with string
print(get_length("hello"))   # 5

# Call with list
print(get_length([1, 2, 3]))  # 3

# Forwarding through intermediate function
def forward(x):
    return get_length(x)

print(forward("ab"))  # 2
print(forward([10, 20, 30, 40]))  # 4

# Mixed-type printing
def show(val):
    """Called with int, str, and list."""
    print(val)

show(42)
show("hello")
show([1, 2])
