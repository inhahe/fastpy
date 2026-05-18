class CompileError:
    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col

class CompileResult:
    def __init__(self, success, executable=None, errors=None):
        self.success = success
        self.executable = executable
        # Variant C: conditional but using an if/else statement instead of ternary
        if errors is not None:
            self.errors = errors
        else:
            self.errors = []

ce1 = CompileError("Syntax error", line=1)
ce2 = CompileError("Unknown feature")
errs = [ce1, ce2]
r2 = CompileResult(False, errors=errs)
x = r2.errors
n = len(x)
print("variant C: len =", n)
