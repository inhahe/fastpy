# Test: no isinstance, just self.env[node.id]
class Name:
    def __init__(self, id):
        self.id = id

class Evaluator:
    def __init__(self):
        self.env = {"x": 10, "y": 20}

    def visit(self, node):
        return self.env[node.id]

ev = Evaluator()
print(ev.visit(Name("x")))
print(ev.visit(Name("y")))
