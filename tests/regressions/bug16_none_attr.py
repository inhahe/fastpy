# Bug 16: self.attr = None corrupts type inference when attr was int
# The mere existence of `self.attr = None` in any method should not
# cause reads of the attr to segfault when the value is actually an int.

class C:
    def __init__(self):
        self._x = 10
    def reset(self):
        self._x = None

c = C()
print(c._x)
c._x = 42
print(c._x)

# With @property
class PropClass:
    def __init__(self):
        self._val = 10
    @property
    def val(self):
        return self._val
    @val.setter
    def val(self, v):
        self._val = v
    @val.deleter
    def val(self):
        self._val = 0  # use 0 instead of None for deleter

pc = PropClass()
print(pc.val)
pc.val = 42
print(pc.val)
del pc.val
print(pc.val)

# Property with None in deleter body
class PropClass2:
    def __init__(self):
        self._data = 100
    @property
    def data(self):
        return self._data
    @data.setter
    def data(self, v):
        self._data = v
    @data.deleter
    def data(self):
        self._data = None

pc2 = PropClass2()
print(pc2.data)
pc2.data = 200
print(pc2.data)
