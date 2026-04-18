# Regression: setting object attribute to True/False printed 1/0
# Before fix: _emit_attr_store's i64 branch didn't check value_node for bool
# constants. True/False are emitted as i64(1)/i64(0), but fell through to
# FPY_TAG_INT. The runtime then printed the integer representation.
# Fix: added value_node checks for bool constants, bool-typed variables,
# comparisons, and _is_bool_typed expressions in _emit_attr_store.

class Config:
    def __init__(self):
        self.value = 0

# Bool constant assignment
c = Config()
c.value = True
print(c.value)
c.value = False
print(c.value)

# Int assignment (should still work)
c.value = 42
print(c.value)

# String assignment
c.value = "hello"
print(c.value)

# Bool from comparison
c.value = 10 > 5
print(c.value)
c.value = 3 > 7
print(c.value)
