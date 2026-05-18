# Test: three classes - just Num and Name calls (no BinOp visit)
class Node:
    pass

class BinOp(Node):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class Num(Node):
    def __init__(self, value):
        self.value = value

class Name(Node):
    def __init__(self, id):
        self.id = id

class Evaluator:
    def __init__(self):
        self.env = {"x": 10, "y": 20}

    def visit(self, node):
        if isinstance(node, Num):
            return node.value
        elif isinstance(node, Name):
            return self.env[node.id]
        elif isinstance(node, BinOp):
            left = self.visit(node.left)
            right = self.visit(node.right)
            if node.op == "+":
                return left + right
        return 0

ev = Evaluator()
print(ev.visit(Num(42)))
print(ev.visit(Name("x")))
