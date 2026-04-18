# Built-in functions and methods test program

# --- any / all ---
print(f"any [1,0,0]: {any([1, 0, 0])}")
print(f"any [0,0,0]: {any([0, 0, 0])}")
print(f"all [1,1,1]: {all([1, 1, 1])}")
print(f"all [1,0,1]: {all([1, 0, 1])}")

# --- list methods ---
nums = [3, 1, 4, 1, 5, 9, 2, 6]
print(f"index of 4: {nums.index(4)}")
print(f"count of 1: {nums.count(1)}")

stack = [10, 20, 30]
val = stack.pop()
print(f"popped: {val}")
print(f"stack: {stack}")

# --- dict methods ---
d = {"name": "Alice", "age": 30}
print(f"get name: {d.get('name', 'unknown')}")
print(f"get email: {d.get('email', 'none')}")
print(f"has name: {'name' in d}")
print(f"has email: {'email' in d}")
print(f"dict len: {len(d)}")

# --- string methods ---
s = "Hello World"
print(f"upper: {s.upper()}")
print(f"lower: {s.lower()}")
print(f"replace: {s.replace('World', 'Python')}")
print(f"starts: {s.startswith('Hello')}")
print(f"ends: {s.endswith('World')}")
print(f"strip: {'  hi  '.strip()}")

# --- string in ---
print(f"'lo' in 'hello': {'lo' in 'hello'}")
print(f"'xyz' in 'hello': {'xyz' in 'hello'}")

# --- sorted with various inputs ---
print(f"sorted: {sorted([5, 2, 8, 1])}")
print(f"reversed: {list(reversed([1, 2, 3]))}")

# --- sum, min, max ---
data = [10, 5, 20, 15, 3]
print(f"sum: {sum(data)}")
print(f"min: {min(data)}")
print(f"max: {max(data)}")

# --- len on various ---
print(f"str len: {len('hello')}")
print(f"list len: {len([1, 2, 3])}")
