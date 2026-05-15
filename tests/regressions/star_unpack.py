# Star unpacking in assignments

# Basic star at end
a, *b = [1, 2, 3, 4]
assert a == 1
assert b == [2, 3, 4]
print("star end ok")

# Star at beginning
*a, b = [1, 2, 3]
assert a == [1, 2]
assert b == 3
print("star begin ok")

# Star in middle
first, *middle, last = [1, 2, 3, 4, 5]
assert first == 1
assert middle == [2, 3, 4]
assert last == 5
print("star middle ok")

# Star with tuple literal
a, *b = (10, 20, 30)
assert a == 10
assert b == [20, 30]
print("star tuple ok")

# Star gets empty list
a, b, *c = [1, 2]
assert a == 1
assert b == 2
assert c == []
print("star empty ok")
