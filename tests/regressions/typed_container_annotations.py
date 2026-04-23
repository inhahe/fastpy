# Regression test for container type annotations with --typed
# compile_flags: --typed
# Annotations like list[int], dict[str, int] provide element type info
# that enables optimized subscript access and iteration.

# list[int] — element access should return int
nums: list[int] = [10, 20, 30]
print(nums[0])     # 10
print(nums[1])     # 20
print(nums[2])     # 30

# list[str] — element access should return str
words: list[str] = ["hello", "world"]
print(words[0])    # hello
print(words[1])    # world

# list[float] — element access should return float
vals: list[float] = [1.5, 2.5, 3.5]
print(vals[0])     # 1.5
print(vals[1])     # 2.5

# Iteration over typed list
total = 0
items: list[int] = [1, 2, 3, 4, 5]
for x in items:
    total = total + x
print(total)       # 15

# String iteration
parts: list[str] = ["a", "b", "c"]
result = ""
for s in parts:
    result = result + s
print(result)      # abc

# dict annotation
counts: dict[str, int] = {"a": 1, "b": 2}
print(counts["a"]) # 1
print(counts["b"]) # 2

# Function with container parameter annotation
def sum_list(data: list[int]) -> int:
    total = 0
    for x in data:
        total = total + x
    return total

print(sum_list([10, 20, 30]))  # 60

# Nested: list of lists
def flatten(matrix: list[list]) -> list:
    result = []
    for row in matrix:
        for x in row:
            result.append(x)
    return result

print(flatten([[1, 2], [3, 4]]))  # [1, 2, 3, 4]
