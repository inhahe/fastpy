# Test that runtime errors (IndexError, KeyError, etc.) are catchable
# exceptions instead of calling exit(1) directly.

# --- IndexError from list subscript ---
try:
    x = [1, 2, 3]
    val = x[10]
    print("FAIL: should not reach")
except IndexError:
    print("caught IndexError: list get")

# --- IndexError from list assignment ---
try:
    x = [1, 2, 3]
    x[10] = 99
    print("FAIL: should not reach")
except IndexError:
    print("caught IndexError: list set")

# --- IndexError from pop ---
try:
    x = []
    x.pop()
    print("FAIL: should not reach")
except IndexError:
    print("caught IndexError: pop empty")

# --- KeyError from dict subscript ---
try:
    d = {"a": 1}
    val = d["missing"]
    print("FAIL: should not reach")
except KeyError:
    print("caught KeyError: dict get")

# --- ValueError from list.remove ---
try:
    x = [1, 2, 3]
    x.remove(99)
    print("FAIL: should not reach")
except ValueError:
    print("caught ValueError: list.remove")

# --- KeyError from dict.pop ---
try:
    d = {"a": 1}
    d.pop("missing")
    print("FAIL: should not reach")
except KeyError:
    print("caught KeyError: dict pop")

# --- Nested function call traceback ---
def inner(lst):
    return lst[5]

def outer(lst):
    return inner(lst)

try:
    outer([1, 2])
    print("FAIL: should not reach")
except IndexError:
    print("caught IndexError: nested call")

print("all exception tests passed")
