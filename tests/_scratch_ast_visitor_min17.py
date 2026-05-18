# Test: method on class, no isinstance, just attr access
class A:
    def __init__(self, val):
        self.val = val

class Visitor:
    def visit(self, node):
        return node.val

v = Visitor()
print(v.visit(A("aaa")))
