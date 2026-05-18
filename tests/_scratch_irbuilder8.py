# Test: __str__ with join returns correctly
class Block:
    def __init__(self, name):
        self.name = name
        self.items = []

    def add(self, s):
        self.items.append(s)

    def __str__(self):
        lines = [self.name + ":"]
        for item in self.items:
            lines.append("  " + item)
        result = "\n".join(lines)
        print("  __str__ returning:", result)
        return result

b = Block("entry")
b.add("line1")
s = str(b)
print("Got:", s)
print("Done")
