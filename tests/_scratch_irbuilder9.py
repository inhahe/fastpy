# Test: Instruction + BasicBlock (no IRBuilder, no _tmp)
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

bb = BasicBlock("entry")
bb.add(Instruction("add", ["a", "b"], "%1"))
print(bb)
