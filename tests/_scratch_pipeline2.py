# Simplified test for IfExp list attribute
class CompileResult:
    def __init__(self, success, errors=None):
        self.success = success
        self.errors = errors if errors is not None else []

# Test 1: errors is a list
r1 = CompileResult(False, errors=["error1", "error2"])
print(r1.success)
print(len(r1.errors))
for e in r1.errors:
    print(e)

# Test 2: errors is None (default)
r2 = CompileResult(True)
print(r2.success)
print(len(r2.errors))
