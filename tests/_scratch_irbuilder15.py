# Test: current alias + list iteration
class Block:
    def __init__(self, name):
        self.name = name
        self.items = []

    def add(self, s):
        self.items.append(s)

    def __str__(self):
        return self.name + ": " + ", ".join(self.items)

class Manager:
    def __init__(self):
        self.blocks = []
        self.current = None

    def new_block(self, name):
        b = Block(name)
        self.blocks.append(b)
        self.current = b
        return b

    def emit(self, s):
        self.current.add(s)

    def dump(self):
        for b in self.blocks:
            print(b)

m = Manager()
m.new_block("entry")
m.emit("x")
m.emit("y")
m.dump()
