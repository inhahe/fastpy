# Debug: exact crash point in __str__ return
class Instruction:
    def __init__(self, opcode, operands, result=None):
        self.opcode = opcode
        self.operands = operands
        self.result = result

    def __str__(self):
        ops = ", ".join(str(o) for o in self.operands)
        print("    step1: ops done:", ops)
        print("    step2: checking result")
        r = self.result
        print("    step3: result is:", r)
        if r:
            print("    step4: result is truthy")
            s = r + " = " + self.opcode + " " + ops
            print("    step5: built:", s)
            return s
        print("    step4b: result is falsy")
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
            print("  BB: calling str(i)")
            s = str(i)
            print("  BB: got:", s)
            lines.append("  " + s)
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
builder.dump()
