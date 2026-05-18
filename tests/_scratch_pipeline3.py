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

# Test
e = CompileError("Not implemented: async", line=5, col=10)
print(e)
r1 = CompileResult(True, executable="/tmp/out.exe")
print(r1)
r2 = CompileResult(False, errors=[
    CompileError("Syntax error", line=1),
    CompileError("Unknown feature"),
])
print(r2)
