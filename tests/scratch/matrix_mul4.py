# Move everything into a function to avoid module-level bare-ABI
def main():
    def make_grid():
        return [[1, 2], [3, 4]]

    g = make_grid()
    for row in g:
        print(row)

main()
