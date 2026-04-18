# Common programming patterns test program

# --- Search function ---
def find_first(lst, target):
    i = 0
    while i < len(lst):
        if lst[i] == target:
            return i
        i += 1
    return -1

data = [10, 20, 30, 40, 50]
print(f"find 30: {find_first(data, 30)}")
print(f"find 99: {find_first(data, 99)}")

# --- Countdown ---
n = 5
result = []
while n > 0:
    result.append(n)
    n -= 1
print(f"countdown: {result}")

# --- Flatten nested list ---
nested = [[1, 2], [3, 4], [5, 6]]
flat = [x for row in nested for x in row]
print(f"flat: {flat}")

# --- Map and filter ---
nums = [1, 2, 3, 4, 5]
doubled = [x * 2 for x in nums]
print(f"doubled: {doubled}")

scores = [45, 82, 67, 91, 55, 73, 88]
passing = [s for s in scores if s >= 60]
print(f"passing: {sorted(passing)}")

# --- Accumulator ---
total = 0
count = 0
for x in [3, 7, 2, 8, 4, 9, 1]:
    if x > 5:
        total += x
        count += 1
if count > 0:
    print(f"avg of big nums: {total // count}")

# --- String building in function ---
def repeat_char(ch, n):
    result = ""
    for i in range(n):
        result = result + ch
    return result

print(f"stars: {repeat_char('*', 10)}")

# --- Multiple return values ---
def min_max(lst):
    lo = lst[0]
    hi = lst[0]
    for x in lst:
        if x < lo:
            lo = x
        if x > hi:
            hi = x
    return lo, hi

lo, hi = min_max([5, 2, 8, 1, 9, 3])
print(f"min={lo}, max={hi}")

# --- Class with methods ---
class Rectangle:
    def __init__(self, w, h):
        self.w = w
        self.h = h
    def area(self):
        return self.w * self.h
    def perimeter(self):
        return 2 * (self.w + self.h)
    def __repr__(self):
        return f"Rect({self.w}x{self.h})"

r = Rectangle(5, 3)
print(f"{r}: area={r.area()}, perimeter={r.perimeter()}")

# --- Exception with recovery ---
def safe_get(lst, idx):
    if idx < 0 or idx >= len(lst):
        raise ValueError("index out of range")
    return lst[idx]

try:
    result = safe_get([10, 20, 30], 5)
    print(result)
except ValueError as e:
    print(f"caught: {e}")

# --- Complex expression ---
print(f"expr: {(2 + 3) * (4 - 1) + 10 // 3}")
