# Bug #119: None == "" (and None vs any pointer type) crashed at runtime
# Bug #120: rsplit() without args crashed
# Bug #121: int * bytes produced TypeError
# Bug #122: bytes.upper()/lower()/strip() crashed (not dispatched)
# Bug #123: bytes slicing printed without b'...' prefix
# Bug #124: bool & bool printed as int instead of bool

# --- None vs pointer-type comparisons ---
assert (None == "") == False
assert (None == "hello") == False
assert ("" == None) == False
assert ("hello" == None) == False
assert (None != "") == True
assert (None != "hello") == True
assert (None == []) == False
assert ([] == None) == False
assert (None == ()) == False
assert (() == None) == False
assert (None == {1}) == False
assert ({1} == None) == False
assert (None == {}) == False
assert ({} == None) == False
assert (None == 0.0) == False
assert (0.0 == None) == False
# Existing None comparisons (regression check)
assert (None == 0) == False
assert (None == None) == True
assert (None != None) == False

# --- rsplit() without args ---
assert "hello world foo".rsplit() == ["hello", "world", "foo"]
assert "  a  b  ".rsplit() == ["a", "b"]

# --- int * bytes ---
assert 3 * b'ab' == b'ababab'
assert b'ab' * 3 == b'ababab'
assert 0 * b'x' == b''
assert b'x' * 0 == b''

# --- bytes methods ---
assert b"hello".upper() == b"HELLO"
assert b"HELLO".lower() == b"hello"
assert b"  hello  ".strip() == b"hello"

# --- bool bitwise operations ---
assert (True & True) == True
assert (True & False) == False
assert (True | False) == True
assert (False | False) == False
assert (True ^ True) == False
assert (True ^ False) == True
# bool & int → int
assert (True & 1) == 1
assert (True | 2) == 3

print("none_cmp_bytes_bool: all assertions passed")
