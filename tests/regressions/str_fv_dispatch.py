# Regression: str()/repr()/f-string on FV variables with dynamic types
# Before fix: str(v), repr(v), f"{v}" crashed (access violation) when v was
# an FV-backed variable whose compile-time tag differed from runtime tag
# (e.g., dict values where compile-time tag was "str" but runtime value was int).
# Fix: use _fv_call_str / _fv_call_repr via runtime tag dispatch instead of
# _value_to_str which blindly interprets by compile-time type.

# str() on mixed dict values
d = {"name": "Alice", "age": 30, "score": 95.5}
for v in d.values():
    print(str(v))

# repr() on mixed dict values
d2 = {"x": 1, "y": "hello"}
for v in d2.values():
    print(repr(v))

# f-string on mixed dict items
person = {"name": "Bob", "age": 25}
for k, v in person.items():
    print(f"  {k}: {v}")

# str() on list elements with mixed types via FV
nums = [10, 20, 30]
for n in nums:
    result = str(n) + "!"
    print(result)

# f-string with int variable (simple case, should still work)
x = 42
print(f"x is {x}")
