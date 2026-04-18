# String methods test program

s = "Hello, World!"

# Basic methods
print(f"lower: {s.lower()}")
print(f"upper: {s.upper()}")

# Strip
padded = "  hello  "
print(f"strip: '{padded.strip()}'")

# Replace
print(f"replace: {s.replace('World', 'Python')}")
print(f"multi replace: {'aabaa'.replace('a', 'x')}")

# Startswith / endswith
print(f"starts H: {s.startswith('Hello')}")
print(f"ends !: {s.endswith('!')}")
print(f"starts X: {s.startswith('X')}")

# String contains (in operator)
print(f"World in s: {'World' in s}")
print(f"xyz in s: {'xyz' in s}")
print(f"not in: {'abc' not in s}")

# Len on various types
print(f"str len: {len(s)}")
print(f"list len: {len([1, 2, 3])}")

d = {"a": 1, "b": 2, "c": 3}
print(f"dict len: {len(d)}")

# List pop
stack = [1, 2, 3, 4, 5]
top = stack.pop()
print(f"popped: {top}")
print(f"remaining: {stack}")

# String building
parts = ["hello", "world"]
result = " ".join(parts)
print(f"joined: {result}")

# Chained operations
words = "  the QUICK brown FOX  "
cleaned = words.strip().lower()
print(f"cleaned: {cleaned}")
