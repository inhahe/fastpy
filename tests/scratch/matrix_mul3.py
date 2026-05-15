# Even simpler: does g get typed correctly after fn return?
def make_grid():
    return [[1, 2], [3, 4]]

g = make_grid()
print(g)        # Does print see it as a list?
print(g[0])     # Does subscript return a list or pointer?
print(g[0][0])  # Nested subscript
