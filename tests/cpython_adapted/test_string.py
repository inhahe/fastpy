# Adapted from CPython Lib/test/test_string.py
# Tests string operations

# Basic operations
s = "hello world"
print(len(s))
print(s[0])
print(s[-1])
print(s[0:5])
print(s[6:])
print(s[:5])

# Methods
print("hello".upper())
print("HELLO".lower())
print("hello world".title())
print("hello world".capitalize())
print("  hello  ".strip())
print("  hello  ".lstrip())
print("  hello  ".rstrip())
print("xxhelloxx".strip("x"))

# Find/index
print("hello world".find("world"))
print("hello world".find("xyz"))
print("hello world".index("world"))
print("hello world".find("l"))
print("hello world".rfind("l"))

# Count
print("hello world".count("l"))
print("hello world".count("o"))
print("aaaaaa".count("aa"))

# Replace
print("hello world".replace("world", "python"))
print("aabbcc".replace("b", "x"))
print("aabbcc".replace("b", "x", 1))

# Split/join
print("a,b,c,d".split(","))
print("hello world foo".split())
print("a::b::c".split("::"))
print(",".join(["a", "b", "c"]))
print(" ".join(["hello", "world"]))
print("".join(["a", "b", "c"]))

# Startswith/endswith
print("hello".startswith("hel"))
print("hello".startswith("xyz"))
print("hello".endswith("llo"))
print("hello".endswith("xyz"))

# isX methods
print("hello".isalpha())
print("hello123".isalpha())
print("12345".isdigit())
print("hello".isdigit())
print("hello123".isalnum())
print("   ".isspace())
print("hello".isspace())
print("HELLO".isupper())
print("hello".islower())

# Formatting
print("x" * 5)
print("ab" * 3)

# String comparison
print("abc" == "abc")
print("abc" == "abd")
print("abc" < "abd")
print("abc" > "abd")
print("abc" < "abcd")
print("" < "a")

# in operator
print("ello" in "hello")
print("xyz" in "hello")
print("" in "hello")

# Concatenation
print("hello" + " " + "world")
print("" + "abc")
print("abc" + "")

# Zfill and center/ljust/rjust
print("42".zfill(5))
print("-42".zfill(5))
print("hello".center(11))
print("hello".ljust(10))
print("hello".rjust(10))
print("hello".center(11, "*"))

# Splitlines
text = "line1\nline2\nline3"
print(text.splitlines())

# Partition
print("hello-world".partition("-"))
print("hello-world-foo".partition("-"))
print("hello".partition("-"))
print("hello-world-foo".rpartition("-"))

# Encode basics (just checking it doesn't crash)
b = "hello"
print(len(b))
print(b[0:3])
