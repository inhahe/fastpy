# Bug #114: isinstance(x, set) always returned True
# Bug #115: None == 0 returned True instead of False
# Bug #116: __bool__ dunder not dispatched through fv_truthy
# Bug #117: str *= n augmented multiply not handled

# --- isinstance fix: set, bytes, complex, frozenset ---
assert isinstance({1, 2}, set) == True
assert isinstance(42, set) == False
assert isinstance("hello", set) == False
assert isinstance([1], set) == False
assert isinstance(3.14, set) == False
assert isinstance(None, set) == False
assert isinstance(True, set) == False

assert isinstance(b"hello", bytes) == True
assert isinstance("hello", bytes) == False
assert isinstance(42, bytes) == False

# --- None comparison fix ---
assert (None == 0) == False
assert (None == False) == False
assert (None == 1) == False
assert (None == None) == True
assert (0 == None) == False
assert (None != 0) == True
assert (None != None) == False

# Bug #119: None compared with pointer types crashed (null ptr deref)
assert (None == "") == False
assert (None == "hello") == False
assert ("" == None) == False
assert ("hello" == None) == False
assert (None != "") == True
assert (None == []) == False
assert ([] == None) == False
assert (None == ()) == False
assert (() == None) == False
assert (None == {1}) == False
assert ({1} == None) == False
assert (None == {}) == False
assert ({} == None) == False
assert (None == 0.0) == False
assert (0.0 == None) == False

# --- __bool__ dunder fix ---
class Truthy:
    def __init__(self, v):
        self.v = v
    def __bool__(self):
        return self.v > 0

t = Truthy(5)
f = Truthy(-5)
assert bool(t) == True
assert bool(f) == False
if t:
    pass
else:
    assert False, "if t: should have been true"
if not f:
    pass
else:
    assert False, "if not f: should have been true"

# --- __len__ truthiness: tested with simple int-returning __len__ ---
# (Note: len(self.items) on object attributes is a pre-existing limitation)
class Sized:
    def __init__(self, n):
        self.n = n
    def __len__(self):
        return self.n

s3 = Sized(3)
s0 = Sized(0)
assert bool(s3) == True
assert bool(s0) == False

# --- str *= n augmented multiply fix ---
s = "ab"
s *= 3
assert s == "ababab", f"str *= 3 got {s!r}"

s = "x"
s *= 0
assert s == "", f"str *= 0 got {s!r}"

s = "hello"
n = 2
s *= n
assert s == "hellohello", f"str *= n got {s!r}"

print("isinstance_none_bool: all assertions passed")
