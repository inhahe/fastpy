# Test: method + 2 isinstance branches, integer attrs (not strings)
class A:
    def __init__(self, val):
        self.val = val

class B:
    def __init__(self, num):
        self.num = num

class Visitor:
    def visit(self, node):
        if isinstance(node, A):
            return node.val
        elif isinstance(node, B):
            return node.num
        return 0

v = Visitor()
print(v.visit(A(42)))
print(v.visit(B(99)))
