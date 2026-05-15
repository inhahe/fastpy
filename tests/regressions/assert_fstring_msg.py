# Regression: assert with dynamic (f-string) message

x = 5
try:
    assert x > 10, f"expected > 10, got {x}"
except AssertionError as e:
    print("caught:", e)

# Variable message
msg = "custom error"
try:
    assert False, msg
except AssertionError as e:
    print("caught:", e)

# String concatenation message
try:
    assert False, "part1" + " part2"
except AssertionError as e:
    print("caught:", e)
