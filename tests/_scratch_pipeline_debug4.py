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
        print("before list literal")
        lines = ["Compilation failed:"]
        print("after list literal, len=", len(lines))
        print("before for loop")
        for e in self.errors:
            print("  in loop")
            lines.append("  " + str(e))
        print("before join")
        return "\n".join(lines)

ce1 = CompileError("Syntax error", line=1)
ce2 = CompileError("Unknown feature")
errs = [ce1, ce2]
r2 = CompileResult(False, errors=errs)
print("calling str(r2)")
s = str(r2)
print("got:", s)
