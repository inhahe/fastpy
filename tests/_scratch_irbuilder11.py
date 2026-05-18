# Test: just _tmp() and Instruction, no BasicBlock.__str__
class Instruction:
    def __init__(self, opcode, operands, result=None):
        self.opcode = opcode
        self.operands = operands
        self.result = result

class IRBuilder:
    def __init__(self):
        self._counter = 0
        self.instructions = []

    def _tmp(self):
        self._counter = self._counter + 1
        return "%" + str(self._counter)

    def do_add(self, a, b):
        r = self._tmp()
        self.instructions.append(Instruction("add", [a, b], r))
        return r

builder = IRBuilder()
t1 = builder.do_add("a", "b")
print("t1:", t1)
print("instr result:", builder.instructions[0].result)
