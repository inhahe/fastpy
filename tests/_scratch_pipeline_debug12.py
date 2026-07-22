class Item:
    def __init__(self, val):
        self.val = val

# Minimal ternary with None default: does 'x if x is not None else []' break len()?
def make_list(items=None):
    return items if items is not None else []

items = [Item(1), Item(2)]
result = make_list(items)
print("len =", len(result))

# Also test it inside a class __init__
class Container:
    def __init__(self, items=None):
        self.items = items if items is not None else []

c = Container(items=[Item(3), Item(4)])
print("len c.items =", len(c.items))
