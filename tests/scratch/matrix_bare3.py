# Test: does subscript work but for-loop doesn't?
def make_grid():
    return [[1, 2], [3, 4]]

g = make_grid()
# Manual iteration via subscript
i = 0
while i < len(g):
    print(g[i])
    i = i + 1
