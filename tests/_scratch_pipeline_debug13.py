class Item:
    def __init__(self, val):
        self.val = val

items = [Item(1), Item(2)]

# Test 1: ternary with None check, result stored in local var
x = None
result1 = items if x is not None else []
print("test1: result when x is None, len =", len(result1))

# Test 2: ternary with non-None, result stored in local var
y = items
result2 = y if y is not None else []
print("test2: result when y is items, len =", len(result2))

# Test 3: ternary directly with items
result3 = items if items is not None else []
print("test3: result3 len =", len(result3))
