# Containers test program
# Tests list, dict, tuple, set operations and comprehensions

# Lists
nums = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
print(f"original: {nums}")
print(f"sorted: {sorted(nums)}")
print(f"reversed: {list(reversed(nums))}")
print(f"unique sorted: {sorted(set(nums))}")
print(f"len: {len(nums)}")
print(f"sum: {sum(nums)}")
print(f"min: {min(nums)}")
print(f"max: {max(nums)}")

# List slicing
print(f"first 3: {nums[:3]}")
print(f"last 3: {nums[-3:]}")
print(f"every 2nd: {nums[::2]}")
print(f"reversed slice: {nums[::-1]}")

# List comprehension
squares = [x * x for x in range(10)]
print(f"squares: {squares}")

evens = [x for x in range(20) if x % 2 == 0]
print(f"evens: {evens}")

# Nested comprehension
matrix = [[i * 3 + j for j in range(3)] for i in range(3)]
print(f"matrix: {matrix}")
flat = [x for row in matrix for x in row]
print(f"flat: {flat}")

# Dicts
person = {"name": "Alice", "age": 30, "city": "NYC"}
print(f"person: {person}")
print(f"name: {person['name']}")
print(f"keys: {sorted(person.keys())}")
print(f"values: {sorted(str(v) for v in person.values())}")

# Dict comprehension
sq_dict = {x: x * x for x in range(6)}
print(f"squares dict: {sq_dict}")

# Dict iteration
for k, v in sorted(person.items()):
    print(f"  {k}: {v}")

# Tuples
point = (3, 4)
x, y = point
print(f"point: {point}, x={x}, y={y}")

# Named unpacking
first, *rest = [1, 2, 3, 4, 5]
print(f"first: {first}, rest: {rest}")

*init, last = [1, 2, 3, 4, 5]
print(f"init: {init}, last: {last}")

# Sets
a = {1, 2, 3, 4}
b = {3, 4, 5, 6}
print(f"union: {sorted(a | b)}")
print(f"intersection: {sorted(a & b)}")
print(f"difference: {sorted(a - b)}")
print(f"symmetric diff: {sorted(a ^ b)}")

# Set comprehension
odd_squares = {x * x for x in range(10) if x % 2 != 0}
print(f"odd squares: {sorted(odd_squares)}")

# Enumerate and zip
names = ["Alice", "Bob", "Charlie"]
scores = [85, 92, 78]
for i, (name, score) in enumerate(zip(names, scores)):
    print(f"  {i}: {name} scored {score}")
