class CompileError:
    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col

class CompileResult:
    def __init__(self, success, errors):
        self.success = success
        self.errors = errors

ce1 = CompileError("Syntax error", line=1)
ce2 = CompileError("Unknown feature")
errs = [ce1, ce2]
print("errs len =", len(errs))
r2 = CompileResult(False, errs)
print("r2 created")
x = r2.errors
print("got x")
n = len(x)
print("len =", n)
