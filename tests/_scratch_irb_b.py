# Test: BasicBlock with terminated flag + Instruction
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

bb = BasicBlock("entry")
bb.add(Instruction("add", ["a", "b"], "%1"))
bb.add(Instruction("ret", ["%2"]))
bb.add(Instruction("nop", []))  # should be ignored (terminated)
print(bb)
