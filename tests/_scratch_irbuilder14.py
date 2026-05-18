# Test: iterating list of objects with __str__
class Block:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name + ":"

class Container:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def dump(self):
        for item in self.items:
            print(item)

c = Container()
c.add(Block("entry"))
c.add(Block("body"))
c.dump()
