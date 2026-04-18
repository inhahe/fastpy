# Regression: dict containing class instances as values.
# Before fix: d["key"] returned the string representation of the obj
# (via fv_str) instead of the obj pointer, causing attr access crashes.

class Item:
    def __init__(self, name, price):
        self.name = name
        self.price = price


# Dict literal with obj values
a = Item("apple", 1)
b = Item("banana", 2)
d = {"a": a, "b": b}
print(d["a"].name)       # expected: apple
print(d["a"].price)      # expected: 1
print(d["b"].name)       # expected: banana

# Dict populated via subscript assignments
inventory = {}
inventory["apple"] = Item("apple", 1)
inventory["banana"] = Item("banana", 2)
print(inventory["apple"].name)
print(inventory["banana"].price)
