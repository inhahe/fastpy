# Regression: function returning dynamically-typed values
# Before fix: function return lost the runtime tag — the FV was unwrapped
# to a bare value using the static return type, then re-wrapped with a
# possibly-wrong tag.  This caused print(get_val(d, "x")) to print a raw
# address instead of 42 when d = {"x": 42, "y": "hello"}.
# Fix: _load_or_wrap_fv emits user function calls as raw FpyValue (no
# unwrap), and _emit_return uses _load_or_wrap_fv for FpyValue returns.

# Function returning dict subscript (mixed-type dict)
def get_val(d, key):
    return d[key]

d = {"x": 42, "y": "hello", "z": 3.14}
print(get_val(d, "x"))
print(get_val(d, "y"))

# Identity function (returns whatever was passed in)
def identity(x):
    return x

print(identity(100))
print(identity("world"))

# Function returning a variable (FV-backed local)
def first_elem(lst):
    for item in lst:
        return item
    return 0

print(first_elem([10, 20, 30]))
print(first_elem(["a", "b", "c"]))
