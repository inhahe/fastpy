# Test: same as 15 but without current=None init
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

    def new_block(self, name):
        b = Block(name)
        self.blocks.append(b)
        return b

    def dump(self):
        for b in self.blocks:
            print(b)

m = Manager()
b = m.new_block("entry")
b.add("x")
b.add("y")
m.dump()
