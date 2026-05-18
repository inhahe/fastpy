# Minimal reproduction: 3 isinstance branches + polymorphic string attrs
class A:
    def __init__(self, x):
        self.x = x

class B:
    def __init__(self, x):
        self.x = x

class C:
    def __init__(self, x):
        self.x = x

def visit(node):
    if isinstance(node, A):
        return node.x
    elif isinstance(node, B):
        return node.x
    elif isinstance(node, C):
        return node.x
    return 0

print(visit(A("aaa")))
print(visit(B("bbb")))
print(visit(C("ccc")))
