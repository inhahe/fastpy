# Test: three isinstance branches but no self.env dict lookup
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
            # Just access node.id directly, no dict lookup
            return node.id
        elif isinstance(node, BinOp):
            return node.op
        return 0

ev = Evaluator()
print(ev.visit(Num(42)))
print(ev.visit(Name("x")))
print(ev.visit(BinOp("+", Num(1), Num(2))))
