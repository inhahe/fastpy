# Test str.format() with positional and keyword args

# Basic positional
print("{} and {}".format("a", "b"))          # a and b
print("{} + {} = {}".format(1, 2, 3))        # 1 + 2 = 3

# Explicit positional indices
print("{0} / {1}".format("num", 100))        # num / 100
print("{1} then {0}".format("second", "first"))  # first then second

# Keyword args
print("{name}".format(name="world"))         # world
print("{name}: {val}".format(name="x", val=10))  # x: 10

# Alignment/fill format spec
print("{0:>10}".format("hi"))                # '        hi'
print("{0:<10}".format("hi"))                # 'hi        '
print("{0:^10}".format("hi"))                # '    hi    '

# Numeric format spec
print("{:.2f}".format(3.14159))              # 3.14
print("{:05d}".format(42))                   # 00042
print("{:+d}".format(42))                    # +42
print("{:+d}".format(-42))                   # -42

# Mixed positional and keyword
print("{0} {greeting}".format("Hello", greeting="world"))  # Hello world
