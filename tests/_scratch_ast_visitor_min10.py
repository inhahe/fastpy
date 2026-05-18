# Test: two isinstance branches - does polymorphic attr access work?
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
    return 0

print(visit(Num(42)))
print(visit(Name("hello")))
