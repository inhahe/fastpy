# Regression test: MatchStar and MatchMapping patterns

# --- MatchStar: case [first, *rest] ---

def classify(seq):
    match seq:
        case [first, *rest]:
            return f"first={first} rest={rest}"
        case []:
            return "empty"
        case _:
            return "other"

print(classify([1, 2, 3]))  # first=1 rest=[2, 3]
print(classify([42]))       # first=42 rest=[]
print(classify([]))          # empty

# MatchStar with suffix
def head_tail(seq):
    match seq:
        case [first, *middle, last]:
            return f"{first}..{middle}..{last}"
        case [only]:
            return f"only={only}"
        case _:
            return "other"

print(head_tail([1, 2, 3, 4]))  # 1..[2, 3]..4
print(head_tail([1, 2]))        # 1..[]..2
print(head_tail([99]))          # only=99

# MatchStar wildcard (unnamed)
def has_three_plus(seq):
    match seq:
        case [_, _, _, *_]:
            return True
        case _:
            return False

print(has_three_plus([1, 2, 3]))     # True
print(has_three_plus([1, 2, 3, 4]))  # True
print(has_three_plus([1, 2]))        # False

# --- MatchMapping: case {"key": val} ---

def describe(data):
    match data:
        case {"name": name, "age": age}:
            return f"{name} is {age}"
        case {"name": name}:
            return f"just {name}"
        case _:
            return "unknown"

print(describe({"name": "Alice", "age": 30}))  # Alice is 30
print(describe({"name": "Bob"}))                # just Bob
print(describe({"x": 1}))                       # unknown
