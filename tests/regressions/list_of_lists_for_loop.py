# Regression: for-loop over function-returned list-of-lists at module level
# Bug: _assign_fv_fast_path used info.ret_tag ("ptr") instead of
# _func_ret_types ("ptr:list"), causing elem_type=INT instead of LIST.
# The F1 GEP optimization then read only the i64 data field (skipping
# the tag), and print wrapped it as INT — printing pointer values
# instead of inner lists.

# Case 1: basic list-of-lists iteration at module level
def make_grid():
    return [[1, 2], [3, 4]]

g = make_grid()
for row in g:
    print(row)

# Case 2: subscript on list-of-lists elements
g2 = make_grid()
for row in g2:
    print(row[0], row[1])

# Case 3: full matrix multiplication
def matmul(A, B):
    n = len(A)
    m = len(B[0])
    p = len(B)
    C = [[0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            s = 0
            for k in range(p):
                s = s + A[i][k] * B[k][j]
            C[i][j] = s
    return C

A = [[1, 2], [3, 4]]
B = [[5, 6], [7, 8]]
C = matmul(A, B)
for row in C:
    print(row)

# Case 4: nested function returning list-of-lists
def main():
    def inner():
        return [[10, 20], [30, 40]]
    result = inner()
    for row in result:
        print(row)

main()

# Case 5: list comprehension producing list-of-lists
def make_identity(n):
    return [[1 if i == j else 0 for j in range(n)] for i in range(n)]

I = make_identity(3)
for row in I:
    print(row)
