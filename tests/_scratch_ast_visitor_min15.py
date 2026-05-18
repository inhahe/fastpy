# Test: method on class + 2 isinstance branches only
class Node:
    pass

class A(Node):
    def __init__(self, val):
        self.val = val

class B(Node):
    def __init__(self, name):
        self.name = name

class Visitor:
    def visit(self, node):
        if isinstance(node, A):
            return node.val
        elif isinstance(node, B):
            return node.name
        return 0

v = Visitor()
print(v.visit(A("aaa")))
print(v.visit(B("bbb")))
