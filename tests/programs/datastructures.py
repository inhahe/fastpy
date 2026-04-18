# Data structures test program
# Tests list manipulation, dict usage, and common patterns

# --- Stack (using list) ---
stack = []
stack.append(1)
stack.append(2)
stack.append(3)
print(f"stack: {stack}")
print(f"top: {stack[-1]}")
print(f"size: {len(stack)}")

# --- Queue simulation with list ---
queue = [10, 20, 30, 40, 50]
print(f"queue: {queue}")
print(f"front: {queue[0]}")

# --- Matrix operations ---
def create_matrix(rows, cols):
    matrix = []
    for i in range(rows):
        row = []
        for j in range(cols):
            row.append(i * cols + j + 1)
        matrix.append(row)
    return matrix

m = create_matrix(3, 3)
print(f"matrix: {m}")

# --- Dict frequency counter ---
text = "hello world hello"
words = text.split()
freq = {}
for w in words:
    if w == "hello":
        freq["hello"] = 2
    elif w == "world":
        freq["world"] = 1
print(f"freq: {freq}")

# --- List filtering ---
nums = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
evens = [x for x in nums if x % 2 == 0]
odds = [x for x in nums if x % 2 != 0]
print(f"evens: {evens}")
print(f"odds: {odds}")

# --- Accumulate pattern ---
def running_sum(lst):
    result = []
    total = 0
    for x in lst:
        total += x
        result.append(total)
    return result

print(f"running sum: {running_sum([1, 2, 3, 4, 5])}")

# --- Zip-like manual ---
keys = ["a", "b", "c"]
vals = [1, 2, 3]
pairs = []
for i in range(len(keys)):
    pairs.append(f"{keys[i]}={vals[i]}")
print(f"pairs: {pairs}")

# --- Nested dict ---
config = {"debug": 1, "verbose": 0, "timeout": 30}
for key in sorted(config.keys()):
    print(f"  {key}: {config[key]}")
