# Test: _tmp() + Instruction.__str__ + BasicBlock.__str__
class Instruction:
    def __init__(self, opcode, operands, result=None):
        self.opcode = opcode
        self.operands = operands
        self.result = result

    def __str__(self):
        ops = ", ".join(str(o) for o in self.operands)
        r = self.result
        if r:
            return r + " = " + self.opcode + " " + ops
        return self.opcode + " " + ops

class BasicBlock:
    def __init__(self, name):
        self.name = name
        self.instructions = []

    def add(self, instr):
        self.instructions.append(instr)

    def __str__(self):
        lines = [self.name + ":"]
        for i in self.instructions:
            s = str(i)
            lines.append("  " + s)
        return "\n".join(lines)

class IRBuilder:
    def __init__(self):
        self._counter = 0
        self.current = None

    def _tmp(self):
        self._counter = self._counter + 1
        return "%" + str(self._counter)

    def do_add(self, a, b):
        r = self._tmp()
        self.current.add(Instruction("add", [a, b], r))
        return r

bb = BasicBlock("entry")
builder = IRBuilder()
builder.current = bb
t1 = builder.do_add("a", "b")
print("before print bb")
print(bb)
print("after print bb")
