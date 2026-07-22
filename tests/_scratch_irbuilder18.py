# Test: Manager creates Block inside method
class Block:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name + ":"

class Manager:
    def __init__(self):
        self.blocks = []

    def new_block(self, name):
        b = Block(name)
        self.blocks.append(b)
        return b

    def dump(self):
        for b in self.blocks:
            print("type check:", type(b))
            print(b)

m = Manager()
b = m.new_block("entry")
print("direct:", b)
m.dump()
