# Regression: list comprehension with BinOp element like [0]*3
# Before fix: _infer_list_elem_type didn't recognize BinOp with a list
# operand as producing a list element, so [[0]*3 for _ in range(3)] was
# tagged as "list:int" instead of "list:list", causing matrix[i][j] = val
# to fail with a type mismatch (inner list pointer treated as int).
# Fix: added BinOp check in _infer_list_elem_type for both List and ListComp.

matrix = [[0] * 3 for _ in range(3)]
for i in range(3):
    for j in range(3):
        matrix[i][j] = i * 3 + j

for row in matrix:
    print(row)

# Also test with list literal containing BinOp elements
grid = [[1] * 2, [2] * 2, [3] * 2]
grid[1][0] = 99
print(grid)
