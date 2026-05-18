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
        print("in __str__, success=", self.success)
        if self.success:
            return "Compiled successfully: " + str(self.executable)
        print("building lines list")
        lines = ["Compilation failed:"]
        print("iterating errors, len=", len(self.errors))
        for e in self.errors:
            print("  visiting error:", e.message)
            s = str(e)
            print("  str(e)=", s)
            lines.append("  " + s)
        print("joining")
        result = "\n".join(lines)
        print("done joining")
        return result

ce1 = CompileError("Syntax error", line=1)
ce2 = CompileError("Unknown feature")
errs = [ce1, ce2]
r2 = CompileResult(False, errors=errs)
print(r2)
