# Test: narrow down - is it node.id or self.env[key]?
class Node:
    pass

class Name(Node):
    def __init__(self, id):
        self.id = id

class Evaluator:
    def __init__(self):
        self.env = {"x": 10, "y": 20}

    def visit(self, node):
        if isinstance(node, Name):
            key = node.id
            print("key:", key)
            val = self.env[key]
            print("val:", val)
            return val
        return 0

ev = Evaluator()
print(ev.visit(Name("x")))
