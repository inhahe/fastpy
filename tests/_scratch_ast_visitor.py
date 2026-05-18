# AST-like node classes (simplified compiler pattern)
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

# Visitor pattern (like codegen)
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
            elif node.op == "-":
                return left - right
            elif node.op == "*":
                return left * right
            elif node.op == "/":
                return left // right
        return 0

# Build AST: (x + y) * 3 - 5
tree = BinOp("-",
    BinOp("*",
        BinOp("+", Name("x"), Name("y")),
        Num(3)),
    Num(5))

ev = Evaluator()
print(ev.visit(tree))
print(ev.visit(BinOp("+", Num(100), Num(200))))
print(ev.visit(Name("x")))
