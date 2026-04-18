# Nested containers

# List of dicts
people = [
    {"name": "alice", "age": 30},
    {"name": "bob", "age": 25},
]
for p in people:
    print(p["name"], p["age"])

# Dict of lists
groups = {
    "even": [2, 4, 6],
    "odd": [1, 3, 5],
}
for k in sorted(groups.keys()):
    total = 0
    for x in groups[k]:
        total = total + x
    print(k, "sum=", total)

# List of tuples
pairs = [(1, "a"), (2, "b"), (3, "c")]
for n, s in pairs:
    print(n, s)

# Nested list
matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
total = 0
for row in matrix:
    for val in row:
        total = total + val
print("matrix sum =", total)

# Dict of dicts
data = {"users": {"alice": 30, "bob": 25}}
print(data["users"]["alice"])
print(data["users"]["bob"])

# (Skipped: list comprehension iterating over list-of-dicts with subscript
#  on loop var — requires deeper loop-var type tracking.)
