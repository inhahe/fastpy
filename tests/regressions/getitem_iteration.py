"""Regression test: iteration via __getitem__ protocol.

Python supports iteration over objects that define __getitem__ but not
__iter__ — it calls __getitem__(0), __getitem__(1), ... until IndexError.

Previously this crashed (access violation) because:
1. The compiler didn't have a __getitem__-based iteration path
2. VKind.OBJ objects fell through to _emit_for_pyobj which expected PyObject*

Also tests that list constructor args are properly typed as containers
(call-site analysis Rule 6), so that self.items[idx] inside __getitem__
works when items was assigned from a parameter.
"""


# Test 1: basic __getitem__ iteration with literal list
class MyList1:
    def __init__(self):
        self.items = [10, 20, 30]
    def __getitem__(self, idx):
        return self.items[idx]

ml1 = MyList1()
for x in ml1:
    print(x)

# Test 2: __getitem__ iteration with constructor parameter
class MyList2:
    def __init__(self, data):
        self.items = data
    def __getitem__(self, idx):
        return self.items[idx]

ml2 = MyList2([100, 200, 300])
for x in ml2:
    print(x)

# Test 3: empty iteration (IndexError on first call)
ml3 = MyList2([])
for x in ml3:
    print(x)
print("empty done")

# Test 4: break in __getitem__ loop
ml4 = MyList2([1, 2, 3, 4, 5])
for x in ml4:
    if x == 3:
        break
    print(x)
print("after break")

# Test 5: for/else (no break → else runs)
ml5 = MyList2([7, 8, 9])
for x in ml5:
    print(x)
else:
    print("else reached")
