# Test: Evaluator with self.env dict + isinstance dispatch
class Node:
    pass

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
        return 0

ev = Evaluator()
print(ev.visit(Num(42)))
print(ev.visit(Name("x")))
