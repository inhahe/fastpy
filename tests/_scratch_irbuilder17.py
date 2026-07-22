# Test: direct append vs method append
class Block:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name + ":"

# Variant 1: direct append
blocks = []
b = Block("entry")
blocks.append(b)
for x in blocks:
    print(x)

# Variant 2: manager method
class Manager:
    def __init__(self):
        self.blocks = []

    def add(self, b):
        self.blocks.append(b)

    def dump(self):
        for b in self.blocks:
            print(b)

print("---")
m = Manager()
m.add(Block("body"))
m.dump()
