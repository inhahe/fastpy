# Regression: *args iteration with non-integer elements
# Bug: *args was typed with elem_type=VKind.INT, causing string and
# other non-integer elements to be treated as integers when iterated.
# Fix: Changed *args element type to VKind.FVALUE in both closure
# (line ~4334) and regular function (line ~8809) paths, and added
# "fvalue" to the from_old_tag string map.

# Case 1: *args with strings
def show(*args):
    for a in args:
        print(a)

show("hello", "world")

# Case 2: *args with integers
def sum_all(*args):
    total = 0
    for a in args:
        total = total + a
    return total

print(sum_all(1, 2, 3))

# Case 3: *args with mixed types via print
def display(*args):
    for item in args:
        print(item)

display(42)
display("text")

# Case 4: *args length
def count_args(*args):
    return len(args)

print(count_args(1, 2, 3))
print(count_args("a", "b"))

# Case 5: *args indexing
def first(*args):
    return args[0]

print(first(99, 88))
