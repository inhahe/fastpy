# Regression test: MatchClass patterns

class Point:
    __match_args__ = ("x", "y")
    def __init__(self, x, y):
        self.x = x
        self.y = y

class Color:
    __match_args__ = ("r", "g", "b")
    def __init__(self, r, g, b):
        self.r = r
        self.g = g
        self.b = b

# --- Keyword patterns: case Point(x=..., y=...) ---

def describe_point(p):
    match p:
        case Point(x=0, y=0):
            return "origin"
        case Point(x=x, y=0):
            return f"x-axis at {x}"
        case Point(x=0, y=y):
            return f"y-axis at {y}"
        case Point(x=x, y=y):
            return f"({x}, {y})"
        case _:
            return "not a point"

print(describe_point(Point(0, 0)))    # origin
print(describe_point(Point(5, 0)))    # x-axis at 5
print(describe_point(Point(0, 3)))    # y-axis at 3
print(describe_point(Point(1, 2)))    # (1, 2)
print(describe_point("hello"))        # not a point

# --- Builtin type patterns: case int(n), case str(s) ---

def type_check(val):
    match val:
        case int(n):
            return f"int: {n}"
        case str(s):
            return f"str: {s}"
        case float(f):
            return f"float: {f}"
        case _:
            return "other"

print(type_check(42))       # int: 42
print(type_check("hello"))  # str: hello
print(type_check(3.14))     # float: 3.14
print(type_check([1, 2]))   # other

# --- Positional patterns: case Point(a, b) ---

def add_points(p):
    match p:
        case Point(x, y):
            return x + y
        case _:
            return 0

print(add_points(Point(3, 4)))   # 7
print(add_points(Point(10, 20))) # 30

# --- Class discrimination ---

def classify(obj):
    match obj:
        case Point(x=x, y=y):
            return f"point({x},{y})"
        case Color(r=r, g=g, b=b):
            return f"color({r},{g},{b})"
        case _:
            return "unknown"

print(classify(Point(1, 2)))       # point(1,2)
print(classify(Color(255, 0, 128))) # color(255,0,128)
print(classify(42))                 # unknown
