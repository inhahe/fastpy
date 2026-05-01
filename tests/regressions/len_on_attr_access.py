# Regression: len() on an attribute access must use the runtime tag from the
# object slot, not a static tag inferred from AST context.
#
# When _infer_type_tag couldn't determine the attribute's container type
# (e.g., self.data = param where param is a list from the call site), the
# fallback path in _to_tag_data_ir stamped the pointer as STR, causing
# fv_len to call str_len on a list pointer and return 0.
#
# The fix: for ast.Attribute arguments, load the full FpyValue from the
# slot (which stores the correct runtime tag) and pass it to fv_len.

class Box:
    def __init__(self, data):
        self.data = data

# List stored as attribute
b1 = Box([1, 2, 3])
print(len(b1.data))  # 3

# Dict stored as attribute
b2 = Box({"a": 1, "b": 2})
print(len(b2.data))  # 2

# String stored as attribute
b3 = Box("hello")
print(len(b3.data))  # 5

# Nested: len on attr of attr's content
class Wrapper:
    def __init__(self, items):
        self.items = items

w = Wrapper([10, 20, 30, 40])
print(len(w.items))  # 4
