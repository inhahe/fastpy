# Test: Instruction with result=None default
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

# With result
i1 = Instruction("add", ["a", "b"], "%1")
print(str(i1))
# Without result (default=None)
i2 = Instruction("ret", ["%2"])
print(str(i2))
