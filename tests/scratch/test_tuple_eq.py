# Test basic tuple equality without generators
a = (1, 2)
b = (1, 2)
print(a == b)       # Should be True
print(a)
print(type(a))

# Test with list (tuples stored as list internally)
c = [1, 2]
print(c == [1, 2])  # Should be True
