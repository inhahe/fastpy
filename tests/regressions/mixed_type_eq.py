# Regression: function called with both int and str args — == must work for both

def check(a, b):
    if a == b:
        print("equal")
    else:
        print("not equal")

# Called with ints
check(3, 3)                # equal
check(3, 5)                # not equal

# Called with strings
check("hello", "hello")   # equal
check("hello", "world")   # not equal
