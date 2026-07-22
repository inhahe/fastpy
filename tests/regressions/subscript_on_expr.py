# Regression: subscript on non-variable list/tuple expressions
# Bug: x = [1,2,3][0] crashed with access violation (segfault).
# Root cause: _assign_fv_fast_path defaulted the element type to
# VKind.OBJ for non-Name/non-Attribute containers (literal lists,
# function call results, etc.). OBJ triggers inline incref which
# dereferences the i64 data as a pointer — crashes for scalar values.
# Fix: infer element type from the container expression instead of
# defaulting to OBJ.

# Case 1: literal list subscript
x = [1, 2, 3][0]
print(x)

# Case 2: literal tuple subscript
x = (10, 20, 30)[1]
print(x)

# Case 3: sorted() result subscript
x = sorted([3, 1, 2])[0]
print(x)

# Case 4: list() wrapping subscript
x = list([4, 5, 6])[2]
print(x)

# Case 5: list(d.keys()) subscript
d = {"a": 1, "b": 2, "c": 3}
k = list(d.keys())[0]
print(k)

# Case 6: list comprehension subscript
x = [i*i for i in range(5)][3]
print(x)

# Case 7: string list subscript
x = ["hello", "world"][1]
print(x)

# Case 8: user function result subscript
def make_list():
    return [100, 200, 300]

x = make_list()[0]
print(x)

# Case 9: sorted(d.keys()) subscript
d2 = {3: "c", 1: "a", 2: "b"}
k = sorted(d2.keys())[0]
print(k, d2[k])

# Case 10: list(d.keys()) + dict subscript
nums = [1, 2, 3]
d3 = {x: x*10 for x in nums}
k = list(d3.keys())[0]
print(d3[k])
