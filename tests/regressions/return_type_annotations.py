# Regression test: return type annotations influence call-site type inference

def make_greeting(name) -> str:
    return "hello " + name

def double_it(x) -> int:
    return x * 2

def to_float(x) -> float:
    return x * 1.5

# Test: return type annotation propagates to call site
greeting = make_greeting("world")
print(greeting.upper())  # HELLO WORLD — requires str type at call site

n = double_it(21)
print(n + 1)  # 43 — requires int type at call site

f = to_float(10)
print(f)  # 15.0

# Test: annotated return types in class methods
class Calculator:
    def __init__(self, value):
        self.value = value

    def get_str(self) -> str:
        return str(self.value)

    def get_doubled(self) -> int:
        return self.value * 2

c = Calculator(42)
s = c.get_str()
print(s.lower())  # 42 — str method works

d = c.get_doubled()
print(d + 8)  # 92
