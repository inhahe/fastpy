# Regression: bytes subscript returns int (byte value), not char
# In CPython, b"hello"[0] returns 104 (int), not 'h' (char)

b = b"hello"
print(b[0])     # 104
print(b[1])     # 101
print(b[4])     # 111

# Negative indexing
print(b[-1])    # 111
print(b[-5])    # 104

# Byte arithmetic
x = b[0] + b[1]
print(x)        # 205
