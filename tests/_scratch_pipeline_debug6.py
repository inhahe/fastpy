class CompileError:
    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col

class CompileResult:
    def __init__(self, success, executable=None, errors=None):
        self.success = success
        self.executable = executable
        self.errors = errors if errors is not None else []

ce1 = CompileError("Syntax error", line=1)
ce2 = CompileError("Unknown feature")
errs = [ce1, ce2]
print("errs created")
r2 = CompileResult(False, errors=errs)
print("r2 created")
x = r2.errors
print("got r2.errors")
print(type(x))
print(len(x))
