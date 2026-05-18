# Test: inheritance from Node + different attr names + 3 isinstance
class Node:
    pass

class A(Node):
    def __init__(self, val):
        self.val = val

class B(Node):
    def __init__(self, name):
        self.name = name

class C(Node):
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
