class Item:
    def __init__(self, val):
        self.val = val

items = [Item(1), Item(2), Item(3)]
print("direct len:", len(items))

# ternary: true branch - items is truthy so this should return items
result = items if items else []
print("ternary len:", len(result))
print("same object?", result is items)

# pure ternary with int lists (no class instances)
nums = [10, 20, 30]
print("nums direct len:", len(nums))
result2 = nums if nums else []
print("nums ternary len:", len(result2))

# ternary with explicit is not None check
result3 = nums if nums is not None else []
print("nums is-not-None ternary len:", len(result3))
