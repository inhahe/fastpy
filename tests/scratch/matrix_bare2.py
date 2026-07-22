# Module level: function return + iteration
def make_grid():
    return [[1, 2], [3, 4]]

g = make_grid()
print("g:", g)
print("g[0]:", g[0])
for row in g:
    print("row:", row)
