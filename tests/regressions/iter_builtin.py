"""Regression test: iter() builtin and list iterator.

Previously iter() on a list/tuple/string just returned the raw container
pointer, which has no __next__ method — causing crashes when next() or
for-loop iteration tried to call __next__ on it.

Fixed by adding a runtime list_iterator type (FpyObj with __iter__ and
__next__ methods) and updating the codegen to create it for iter() calls.
"""


# Test 1: iter() + next()
it = iter([10, 20, 30])
print(next(it))
print(next(it))
print(next(it))

# Test 2: for loop over iter()
for x in iter([1, 2, 3]):
    print(x)

# Test 3: iter() on string
for ch in iter("abc"):
    print(ch)

# Test 4: iter() on tuple
for x in iter((100, 200)):
    print(x)

# Test 5: iter() on range
for x in iter(range(3)):
    print(x)

# Test 6: iter() stored in variable
it2 = iter([4, 5, 6])
for x in it2:
    print(x)

# Test 7: class with __iter__ returning iter(self.items)
class MyList:
    def __init__(self):
        self.items = [7, 8, 9]
    def __iter__(self):
        return iter(self.items)

for x in MyList():
    print(x)

# Test 8: class with both __getitem__ and __iter__
class SeqBoth:
    def __init__(self):
        self.data = [11, 22, 33]
    def __getitem__(self, idx):
        return self.data[idx]
    def __iter__(self):
        return iter(self.data)

for x in SeqBoth():
    print(x)
