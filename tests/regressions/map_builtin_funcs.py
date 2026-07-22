"""Regression test: map() with builtin functions.

Previously map(int, ...) and map(str, ...) didn't properly convert
elements — they just copied raw i64 data with the wrong tag, resulting
in garbage values (raw pointers for int conversion, raw IEEE 754 bits
for str conversion of floats).
"""


# map(int, strings) — should parse strings to ints
result1 = list(map(int, ['1', '2', '3']))
print(result1)

# map(int, floats) — should truncate
result2 = list(map(int, [1.5, 2.7, 3.9]))
print(result2)

# map(str, mixed) — should convert each type properly
result3 = list(map(str, [1, 2.5, 3]))
print(result3)

# map(str, strings) — passthrough
result4 = list(map(str, ['hello', 'world']))
print(result4)

# map(float, ints) — should convert
result5 = list(map(float, [1, 2, 3]))
print(result5)

# map with lambda
result6 = list(map(lambda x: x * 2, [1, 2, 3]))
print(result6)
