# Regression: for k in d: d[k] with integer-keyed dicts
# Bug: _emit_for_dict defaulted key_type to "str" for all dicts,
# causing int keys to be treated as string pointers. The loop
# variable was typed STR, so d[k] used string-based lookup on
# garbage pointer values → segfault.
# Fix: check _is_int_keyed_dict() and dict literal key types.

# Case 1: int-keyed dict literal iteration + subscript
d1 = {0: "a", 1: "b", 2: "c"}
for k in d1:
    print(k, d1[k])

# Case 2: int-keyed dict comprehension
d2 = {i: i * i for i in range(5)}
for k in d2:
    print(k, d2[k])

# Case 3: str-keyed dict (should still work)
d3 = {"x": 10, "y": 20}
for k in d3:
    print(k, d3[k])

# Case 4: int-keyed dict with mixed value types
d4 = {1: "hello", 2: "world", 3: "!"}
for k in d4:
    print(k, d4[k])
