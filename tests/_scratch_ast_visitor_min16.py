# Test: method on class + 1 isinstance branch
class A:
    def __init__(self, val):
        self.val = val

class Visitor:
    def visit(self, node):
        if isinstance(node, A):
            return node.val
        return 0

v = Visitor()
print(v.visit(A("aaa")))
