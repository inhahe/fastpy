# String methods and operations test program

# --- Basic methods ---
s = "Hello, World!"
print(f"length: {len(s)}")
print(f"lower: {s.lower()}")
print(f"index 0: {s[0]}")
print(f"index -1: {s[-1]}")
print(f"slice: {s[0:5]}")

# --- String building ---
parts = []
for i in range(5):
    parts.append(f"item{i}")
result = ", ".join(parts)
print(f"joined: {result}")

# --- String iteration ---
upper_count = 0
for ch in "Hello World":
    if ch == "H" or ch == "W":
        upper_count += 1
print(f"uppercase starts: {upper_count}")

# --- String in expressions ---
name = "Alice"
greeting = "Hello, " + name + "!"
print(greeting)

# --- String repeat ---
line = "-" * 20
print(line)

# --- String comparison ---
print(f"equal: {'abc' == 'abc'}")
print(f"not equal: {'abc' != 'def'}")

# --- F-strings with expressions ---
x = 42
y = 3.14
print(f"int: {x}, float: {y}")
print(f"expr: {x * 2 + 1}")
print(f"bool: {x > 40}")

# --- Split and join ---
sentence = "the quick brown fox"
words = sentence.split()
reversed_words = []
for i in range(len(words)):
    reversed_words.append(words[len(words) - 1 - i])
print(" ".join(reversed_words))

# --- Multi-line string building ---
lines = []
for i in range(1, 4):
    lines.append(f"Line {i}")
print("\n".join(lines))
