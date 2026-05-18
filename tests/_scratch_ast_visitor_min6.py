# Test: two classes + isinstance dispatch + self.env
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
            print("Num branch, value=", node.value)
            return node.value
        elif isinstance(node, Name):
            print("Name branch, id=", node.id)
            key = node.id
            print("key type:", type(key))
            print("key:", key)
            val = self.env[key]
            print("val:", val)
            return val
        return 0

ev = Evaluator()
print("--- test Num ---")
print(ev.visit(Num(42)))
print("--- test Name ---")
print(ev.visit(Name("x")))
