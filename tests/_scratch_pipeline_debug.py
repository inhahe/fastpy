class CompileError:
    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col
    def __str__(self):
        loc = ""
        if self.line is not None:
            loc = " (line " + str(self.line)
            if self.col is not None:
                loc = loc + ", col " + str(self.col)
            loc = loc + ")"
        return self.message + loc

class CompileResult:
    def __init__(self, success, executable=None, errors=None):
        self.success = success
        self.executable = executable
        self.errors = errors if errors is not None else []
    def __str__(self):
        if self.success:
            return "Compiled successfully: " + str(self.executable)
        lines = ["Compilation failed:"]
        for e in self.errors:
            lines.append("  " + str(e))
        return "\n".join(lines)

# Test step 1 - just CompileError with line+col
print("step1")
e = CompileError("Not implemented: async", line=5, col=10)
print(e)

# Test step 2 - CompileResult(True)
print("step2")
r1 = CompileResult(True, executable="/tmp/out.exe")
print(r1)

# Test step 3 - Create CompileError with only line= (col=None)
print("step3")
ce1 = CompileError("Syntax error", line=1)
print(ce1)

# Test step 4 - Create CompileError with no args
print("step4")
ce2 = CompileError("Unknown feature")
print(ce2)

# Test step 5 - Build list
print("step5")
errs = [ce1, ce2]
print("list built")

# Test step 6 - CompileResult(False) with pre-built list
print("step6")
r2 = CompileResult(False, errors=errs)
print("r2 created")

# Test step 7 - print r2
print("step7")
print(r2)
