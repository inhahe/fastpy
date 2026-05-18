# Test: constructor called from method, attribute accessed in __str__
class Instruction:
    def __init__(self, opcode, result=None):
        self.opcode = opcode
        self.result = result

    def __str__(self):
        if self.result:
            return self.result + " = " + self.opcode
        return self.opcode

class Builder:
    def __init__(self):
        self._counter = 0

    def _tmp(self):
        self._counter = self._counter + 1
        return "%" + str(self._counter)

    def emit(self, opcode):
        r = self._tmp()
        instr = Instruction(opcode, r)
        return instr

b = Builder()
i = b.emit("add")
print(str(i))
