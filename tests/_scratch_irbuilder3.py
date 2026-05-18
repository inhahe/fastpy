# Debug: track return values through method chain
class BasicBlock:
    def __init__(self, name):
        self.name = name
        self.instructions = []

    def add(self, instr):
        self.instructions.append(instr)

class IRBuilder:
    def __init__(self):
        self.current = None
        self._counter = 0

    def new_block(self, name):
        bb = BasicBlock(name)
        self.current = bb
        return bb

    def _tmp(self):
        self._counter = self._counter + 1
        result = "%" + str(self._counter)
        print("  _tmp returns:", result)
        return result

    def do_add(self, a, b):
        r = self._tmp()
        print("  do_add: r =", r)
        return r

builder = IRBuilder()
entry = builder.new_block("entry")
t1 = builder.do_add("a", "b")
print("t1:", t1)
