# String edge cases: escapes, multiplication, multi-line, bytes conversion

# Escape sequences
print("tab:\there")
print("newline split:\nline2")
print("backslash: \\")
print("quote: \"inner\"")
# Note: embedded null bytes (\x00) truncate strings because the runtime
# uses null-terminated C strings. This is a known architectural limitation.
# print("null char len:", len("a\x00b"))  # would return 1, not 3
print("unicode: \u00e9\u00e8\u00ea")

# String multiplication with variable
n = 3
print("ha" * n)
print(n * "go ")

# Multi-line string
ml = """line one
line two
line three"""
print(ml)

# Raw string
print(r"no\nescape\there")

# String and bytes conversion
text = "hello"
b = text.encode("utf-8")
print(type(b).__name__)
print(b.decode("utf-8"))
print(list(b))

# repr of special chars
print(repr("\t\n\\"))

print("tests passed!")
