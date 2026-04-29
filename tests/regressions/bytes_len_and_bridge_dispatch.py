# Regression: bytes len() and bridge call result dispatch
# Tests that len() works on bytes literals and that bridge call results
# can be printed and measured correctly.

# 1. Bytes literal len
data = b"hello"
print(len(data))    # 5

# 2. Bytes literal operations
print(b"ab" + b"cd")   # b'abcd'
print(b"ab" * 3)       # b'ababab'

# 3. Bytes subscript
print(b"hello"[0])     # h

# 4. Bytes in
print(b"h" in b"hello")  # True

# 5. Bridge call result: from-import, use result
from zipfile import is_zipfile
print(is_zipfile("nonexist.zip"))  # False

# 6. Bridge call result: from-import, len on string result
from os.path import basename
name = basename("/foo/bar.py")
print(len(name))   # 6
print(name)         # bar.py

# 7. Bridge call: from-import with multiple names
from itertools import chain
result = list(chain([1, 2], [3, 4]))
print(result)       # [1, 2, 3, 4]
