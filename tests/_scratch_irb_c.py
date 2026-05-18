# Test: Full with IRBuilder + current=None + new_block + chained ops
class Instruction:
    def __init__(self, opcode, operands, result=None):
        self.opcode = opcode
        self.operands = operands
        self.result = result

    def __str__(self):
        ops = ", ".join(str(o) for o in self.operands)
        if self.result:
            return self.result + " = " + self.opcode + " " + ops
        return self.opcode + " " + ops

class BasicBlock:
    def __init__(self, name):
        self.name = name
        self.instructions = []
        self.terminated = False

    def add(self, instr):
        if not self.terminated:
            self.instructions.append(instr)
        if instr.opcode in ("ret", "br", "cbr"):
            self.terminated = True

    def __str__(self):
        lines = [self.name + ":"]
        for i in self.instructions:
            lines.append("  " + str(i))
        return "\n".join(lines)

class IRBuilder:
    def __init__(self):
        self.blocks = []
        self.current = None
        self._counter = 0

    def new_block(self, name):
        bb = BasicBlock(name)
        self.blocks.append(bb)
        self.current = bb
        return bb

    def _tmp(self):
        self._counter = self._counter + 1
        return "%" + str(self._counter)

    def do_add(self, a, b):
        r = self._tmp()
        self.current.add(Instruction("add", [a, b], r))
        return r

    def dump(self):
        for bb in self.blocks:
            print(bb)

builder = IRBuilder()
entry = builder.new_block("entry")
t1 = builder.do_add("a", "b")
print("t1:", t1)
builder.dump()
