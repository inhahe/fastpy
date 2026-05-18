# Test: isinstance dispatch chain with polymorphic method
class Node:
    pass

class Num(Node):
    def __init__(self, value):
        self.value = value

class Name(Node):
    def __init__(self, id):
        self.id = id

def visit(node):
    if isinstance(node, Num):
        return node.value
    elif isinstance(node, Name):
        return node.id
    return "unknown"

print(visit(Num(42)))
print(visit(Name("hello")))
