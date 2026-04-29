# Bug #113: str * bool and bool * str should treat bool as int
# In Python, True == 1 and False == 0 for sequence repeat operations.
# Previously, str*bool and bool*str raised TypeError instead of repeating.

# str * True → original string (1 repeat)
result = "abc" * True
assert result == "abc", f"'abc' * True = {result!r}, expected 'abc'"

# str * False → empty string (0 repeats)
result = "hello" * False
assert result == "", f"'hello' * False = {result!r}, expected ''"

# True * str → same as str * 1
result = True * "xyz"
assert result == "xyz", f"True * 'xyz' = {result!r}, expected 'xyz'"

# False * str → same as str * 0
result = False * "test"
assert result == "", f"False * 'test' = {result!r}, expected ''"

# Boolean variables (not just literals)
b = True
result = "repeat" * b
assert result == "repeat", f"'repeat' * b = {result!r}, expected 'repeat'"

b = False
result = b * "gone"
assert result == "", f"b * 'gone' = {result!r}, expected ''"

# list * bool should also work (verify no regression)
lst = [1, 2, 3]
assert lst * True == [1, 2, 3], f"[1,2,3] * True failed"
assert lst * False == [], f"[1,2,3] * False failed"
assert True * lst == [1, 2, 3], f"True * [1,2,3] failed"
assert False * lst == [], f"False * [1,2,3] failed"

# bool arithmetic still works (True + True = 2, not TypeError)
assert True + True == 2
assert True * True == 1
assert False + True == 1
assert True - False == 1

# str * int still works
assert "ab" * 3 == "ababab"
assert 2 * "cd" == "cdcd"
assert "x" * 0 == ""

print("str_bool_repeat: all assertions passed")
