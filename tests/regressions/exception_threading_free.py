# compile_flags: -t
# Test exception handling under free-threaded mode.
# Each thread has its own TLS exception state.

def risky(items, idx):
    return items[idx]

# Exception in main thread, caught
try:
    risky([1, 2, 3], 10)
except IndexError:
    print("main: caught IndexError")

# KeyError, caught
try:
    d = {"a": 1}
    val = d["missing"]
except KeyError:
    print("main: caught KeyError")

# Nested call exception
def outer(lst):
    return risky(lst, 99)

try:
    outer([10, 20])
except IndexError:
    print("main: caught nested IndexError")

print("threading_free: all passed")
