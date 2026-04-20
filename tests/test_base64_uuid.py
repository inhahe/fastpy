"""Test base64 and uuid modules."""
import base64
import uuid

# base64 encode/decode
encoded = base64.b64encode("Hello, World!")
print(encoded)  # SGVsbG8sIFdvcmxkIQ==

decoded = base64.b64decode(encoded)
print(decoded)  # Hello, World!

# Roundtrip
original = "fastpy AOT compiler"
assert_eq = base64.b64decode(base64.b64encode(original))
print(assert_eq)  # fastpy AOT compiler

# uuid4 — random UUID
id1 = uuid.uuid4()
print(len(id1))   # 36 (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)

# Each call should produce different UUIDs
id2 = uuid.uuid4()
print(id1 != id2)  # True (astronomically unlikely to collide)

# Check format: has 4 hyphens at correct positions
print(id1[8] == "-")   # True
print(id1[13] == "-")  # True

print("base64/uuid tests passed!")
