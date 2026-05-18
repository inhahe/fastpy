# Adapted from CPython Lib/test/test_str.py (method tests)
# Tests string methods more thoroughly

# split
print("a,b,c".split(","))
print("a,,b,,c".split(","))
print("hello world".split())
print("  hello  world  ".split())
print("one".split(","))
print("".split(","))
print("a:b:c:d".split(":", 2))
print("a b c d e".split(None, 2))

# rsplit
print("a,b,c,d".rsplit(",", 2))
print("a b c d e".rsplit(None, 2))

# join
print(",".join(["a", "b", "c"]))
print("".join(["x", "y", "z"]))
print(" ".join([]))
print("--".join(["one"]))
print("|".join(["a", "b", "c", "d"]))

# replace
print("hello world".replace("world", "python"))
print("aaa".replace("a", "bb"))
print("aaa".replace("a", "bb", 2))
print("hello".replace("x", "y"))
print("".replace("", "x"))

# strip/lstrip/rstrip
print("  hello  ".strip())
print("  hello  ".lstrip())
print("  hello  ".rstrip())
print("xxhelloxx".strip("x"))
print("xxhelloxx".lstrip("x"))
print("xxhelloxx".rstrip("x"))
print("hello".strip())

# upper/lower/title/capitalize/swapcase
print("hello".upper())
print("HELLO".lower())
print("hello world".title())
print("hello world".capitalize())
print("Hello World".swapcase())

# startswith/endswith
print("hello world".startswith("hello"))
print("hello world".startswith("world"))
print("hello world".endswith("world"))
print("hello world".endswith("hello"))
print("hello".startswith(""))
print("hello".endswith(""))

# find/rfind/index/rindex
print("hello world".find("world"))
print("hello world".find("xyz"))
print("hello world".find("o"))
print("hello world".rfind("o"))
print("hello world".find("l"))
print("hello world".rfind("l"))
print("hello".find("", 3))

# count
print("hello world".count("l"))
print("hello world".count("o"))
print("aaaaaa".count("aa"))
print("hello".count(""))

# isX methods
print("hello".isalpha())
print("hello123".isalpha())
print("12345".isdigit())
print("12.34".isdigit())
print("hello123".isalnum())
print("   ".isspace())
print("\t\n".isspace())
print("hello".isspace())
print("HELLO".isupper())
print("Hello".isupper())
print("hello".islower())
print("Hello".islower())

# zfill
print("42".zfill(5))
print("42".zfill(1))
print("-42".zfill(5))
print("+42".zfill(5))

# center/ljust/rjust
print("hi".center(10))
print("hi".center(10, "*"))
print("hi".ljust(10))
print("hi".ljust(10, "-"))
print("hi".rjust(10))
print("hi".rjust(10, "0"))
print("hello".center(3))

# partition/rpartition
print("hello-world".partition("-"))
print("hello".partition("-"))
print("a-b-c-d".partition("-"))
print("a-b-c-d".rpartition("-"))

# expandtabs
print("a\tb\tc".expandtabs(4))
print("\t\t".expandtabs(4))

# Chaining methods
print("  Hello, World!  ".strip().lower().replace(",", "").split())
