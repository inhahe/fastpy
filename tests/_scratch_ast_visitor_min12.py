# Minimal: 3 isinstance branches + DIFFERENT attr names
class A:
    def __init__(self, val):
        self.val = val

class B:
    def __init__(self, name):
        self.name = name

class C:
    def __init__(self, op):
        self.op = op

def visit(node):
    if isinstance(node, A):
        return node.val
    elif isinstance(node, B):
        return node.name
    elif isinstance(node, C):
        return node.op
    return 0

print(visit(A("aaa")))
print(visit(B("bbb")))
print(visit(C("ccc")))
