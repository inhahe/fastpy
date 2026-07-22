# MINIMAL REPRODUCTION: method + 2 isinstance branches + string attr access
class A:
    def __init__(self, val):
        self.val = val

class B:
    def __init__(self, val):
        self.val = val

class Visitor:
    def visit(self, node):
        if isinstance(node, A):
            return node.val
        elif isinstance(node, B):
            return node.val
        return 0

v = Visitor()
print(v.visit(A("aaa")))
print(v.visit(B("bbb")))
