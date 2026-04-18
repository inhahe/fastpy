# Feature coverage test program
# Tests various Python features to find gaps

# --- Global state ---
counter = 0

def increment():
    global counter
    counter += 1
    return counter

print(f"counter: {increment()}, {increment()}, {increment()}")

# --- String iteration ---
vowels = 0
for ch in "hello world":
    if ch == "a" or ch == "e" or ch == "i" or ch == "o" or ch == "u":
        vowels += 1
print(f"vowels: {vowels}")

# --- Negative indexing ---
nums = [10, 20, 30, 40, 50]
print(f"last: {nums[-1]}")
print(f"second to last: {nums[-2]}")

# --- String methods ---
s = "  Hello, World!  "
print(f"strip would be: Hello, World!")
print(f"upper check: {s[2] == 'H'}")

# --- Chained string operations ---
words = "the quick brown fox"
result = "-".join(words.split())
print(f"joined: {result}")

# --- Nested function calls ---
print(f"max of sorted: {sorted([3, 1, 4, 1, 5])[4]}")

# --- Mixed arithmetic ---
print(f"int div: {7 // 2}")
print(f"true div: {7 / 2}")
print(f"mod: {7 % 3}")
print(f"neg div: {-7 // 2}")
print(f"neg mod: {-7 % 2}")
print(f"pow: {2 ** 10}")
print(f"float: {1.5 + 2.5}")

# --- Boolean expressions ---
x = 5
print(f"ternary: {'yes' if x > 3 else 'no'}")
print(f"chain: {1 < x < 10}")

# --- Multiple assignment ---
a = b = c = 42
print(f"multi: {a}, {b}, {c}")

# --- List operations ---
lst = [1, 2, 3, 4, 5]
print(f"sum: {sum(lst)}")
print(f"len: {len(lst)}")
print(f"min: {min(lst)}")
print(f"max: {max(lst)}")

# --- Empty containers ---
empty_list = []
empty_dict = {}
print(f"empty list: {empty_list}")
print(f"empty dict: {empty_dict}")

# --- Nested dicts ---
data = {"name": "Alice", "scores": [85, 92, 78]}
print(f"name: {data['name']}")
