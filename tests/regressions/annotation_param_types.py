# Regression test: always-on parameter type annotations
# No special compile flags needed — annotations are read without --typed.
# Tests that annotations enable correct method dispatch INSIDE the function.

from pathlib import Path

# --- Path annotation enables .name/.stem/.suffix/.parent dispatch ---

def get_filename(p: Path) -> str:
    return p.name

def get_stem(p: Path) -> str:
    return p.stem

def get_suffix(p: Path) -> str:
    return p.suffix

# Chained: p.parent.name
def get_parent_name(p: Path) -> str:
    return p.parent.name

print(get_filename(Path("hello.py")))       # hello.py
print(get_stem(Path("hello.py")))           # hello
print(get_suffix(Path("hello.py")))         # .py
print(get_parent_name(Path("/some/deep")))  # some

# Path with intermediate variable
def parent_str(p: Path) -> str:
    parent = p.parent
    return str(parent)

print(parent_str(Path("/foo/bar")))  # \foo

# --- Scalar annotations ---

def add_floats(a: float, b: float) -> float:
    return a + b

print(add_floats(1.5, 2.5))  # 4.0

def greet(name: str) -> str:
    return "Hello, " + name

print(greet("world"))  # Hello, world

def negate(flag: bool) -> bool:
    return not flag

print(negate(True))   # False
print(negate(False))  # True

# --- User class annotation: attribute access inside function ---

class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

def get_x(p: Point):
    return p.x

def get_y(p: Point):
    return p.y

pt = Point(10, 20)
print(get_x(pt))   # 10
print(get_y(pt))    # 20

# --- enumerate with start= keyword argument ---

items = ["a", "b", "c"]
for i, v in enumerate(items, start=5):
    print(i, v)
# 5 a
# 6 b
# 7 c
