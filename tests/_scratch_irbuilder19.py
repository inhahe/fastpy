# Simplest param forwarding test
class Item:
    def __init__(self, name):
        self.name = name

class Container:
    def __init__(self):
        self.items = []

    def add(self, name):
        item = Item(name)
        self.items.append(item)

c = Container()
c.add("hello")
print(c.items[0].name)
