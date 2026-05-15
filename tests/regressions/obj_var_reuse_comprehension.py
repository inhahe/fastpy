# Regression: OBJ variable name reused as list comprehension loop variable
# The OBJ-preservation guard in _store_variable must not interfere when
# a loop counter genuinely holds an integer (e.g. from range()).
# Previously this caused a segfault: the guard forced the type to OBJ,
# and the refcount code tried to dereference small integers as pointers.

class Foo:
    pass

# Case 1: basic list comp reuse
x = Foo()
print(type(x).__name__)
result = [x for x in range(3)]
print(result)

# Case 2: nested list comp reuse
y = Foo()
matrix = [[y for y in range(3)] for x in range(2)]
print(matrix)

# Case 3: for loop reuse (should also work)
z = Foo()
for z in range(4):
    pass
print(z)
