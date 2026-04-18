for i, row in enumerate([[1, 2], [3, 4]]):
    for j, x in enumerate(row):
        print(i, j, x)

print("---")

for i, row in enumerate([[10, 20], [30, 40]]):
    for j, x in zip([100, 200], row):
        print(i, j, x)

print("---")

grid = {"a": [(1, 2), (3, 4)], "b": [(5, 6), (7, 8)]}
for k in sorted(grid):
    for x, y in grid[k]:
        print(k, x, y)
