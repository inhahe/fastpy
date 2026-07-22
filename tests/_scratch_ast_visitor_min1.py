# Minimal test: dict with string keys + class attribute access
class Num:
    def __init__(self, value):
        self.value = value

class Name:
    def __init__(self, id):
        self.id = id

# Test 1: basic dict with string keys
env = {"x": 10, "y": 20}
print(env["x"])
print(env["y"])

# Test 2: isinstance dispatch
n = Num(42)
m = Name("hello")
print(isinstance(n, Num))
print(isinstance(m, Name))

# Test 3: class attribute access
print(n.value)
print(m.id)
