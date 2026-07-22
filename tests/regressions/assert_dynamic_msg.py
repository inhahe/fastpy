# Regression: assert with various message types

# Constant message (already covered)
try:
    assert False, "static message"
except AssertionError as e:
    print("caught:", e)

# No message
try:
    assert 0
except AssertionError as e:
    print("no msg:", type(e).__name__)

# Assert with True (should NOT raise)
assert True, "this should not appear"
assert 1
assert "nonempty"
print("assertions passed")
