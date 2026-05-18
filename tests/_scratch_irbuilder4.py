# Minimal: test _tmp() returns string, then str concat
class IRBuilder:
    def __init__(self):
        self._counter = 0

    def _tmp(self):
        self._counter = self._counter + 1
        return "%" + str(self._counter)

builder = IRBuilder()
t = builder._tmp()
print(t)
print(type(t))
